# encoding: utf-8
import cStringIO
import pandas
import logging
import datetime
import json
import re
import requests
from sqlalchemy.orm.exc import NoResultFound
from goodtables import validate
from ckan.common import _
from ckan.model import Session
import ckan.lib.uploader as uploader
import ckantoolkit as t
import shapefile
import zipfile
from helpers import validation_load_json_schema
from collections import OrderedDict
from ckanext.validation.model import Validation
from custom_checks import setup_custom_goodtables

log = logging.getLogger(__name__)


def run_validation_job(resource):

    log.debug(u'Validating resource {}'.format(resource['id']))

    try:
        validation = Session.query(Validation).filter(
            Validation.resource_id == resource['id']).one()
    except NoResultFound:
        validation = None

    if not validation:
        validation = Validation(resource_id=resource['id'])

    validation.status = u'running'
    Session.add(validation)
    Session.commit()

    options = t.config.get(
        u'ckanext.validation.default_validation_options')
    if options:
        options = json.loads(options)
    else:
        options = {}

    resource_options = resource.get(u'validation_options')
    if resource_options and isinstance(resource_options, basestring):
        resource_options = json.loads(resource_options)
    if resource_options:
        options.update(resource_options)

    dataset = t.get_action('package_show')(
        {'ignore_auth': True},
        {'id': resource['package_id']}
    )

    source = None
    if resource.get(u'url_type') == u'upload':
        upload = uploader.get_resource_uploader(resource)
        if isinstance(upload, uploader.ResourceUpload):
            source = upload.get_path(resource[u'id'])
        else:
            # Upload is not the default implementation (ie it's a cloud storage
            # implementation)
            pass_auth_header = t.asbool(
                t.config.get(u'ckanext.validation.pass_auth_header', True))
            if dataset[u'private'] and pass_auth_header:
                s = requests.Session()
                s.headers.update({
                    u'Authorization': t.config.get(
                        u'ckanext.validation.pass_auth_header_value',
                        _get_site_user_api_key())
                })

                options[u'http_session'] = s

    if not source:
        source = resource[u'url']

    # Load the the schema as a dictionary
    schema = resource.get(u'schema')
    if schema and isinstance(schema, basestring):
        schema = validation_load_json_schema(schema)

    # Load the data as a dataframe
    _format = resource.get(u'format', u'').lower()
    original_df = _load_dataframe(source, _format)
    actual_headers = original_df.columns

    # Some of the tables (lists of indicators) are transposed for readability
    altered_df = original_df.copy()
    if schema.get("transpose"):
        altered_df = _transpose_dataframe(original_df)

    # For e.g. geojson there is no specified column ordering in the input.
    # Here we reorder columns if necessary for Goodtables to process.
    column_mapping = {}
    if not schema.get('require_field_order', True):
        altered_df, column_mapping = _reorder_columns(schema, altered_df)

    # Ingest NA values
    if schema.get("naValue"):
        altered_df = _remove_na(schema["naValue"], altered_df)

    # Foreign keys requires using resource metadata in validation step
    # We insert the metadata into schema here
    if schema.get("foreignKeys"):
        _prep_foreign_keys(dataset, schema, resource, altered_df)

    # Having extracted/altered data, we wrap up as an excel StringIO.
    # This keeps dataframe in memory, rather than having to write back to disk.
    source = _excel_string_io_wrapper(altered_df)
    report = _validate_table(source, _format='xlsx', schema=schema, **options)

    # Hide uploaded files
    for table in report.get('tables', []):
        if table['source'].startswith('/'):
            table['source'] = resource['url']
    for index, warning in enumerate(report.get('warnings', [])):
        report['warnings'][index] = re.sub(r'Table ".*"', 'Table', warning)

    # If table's columns reordered, correct the column ordering in report
    if column_mapping:
        report['tables'][0]['errors'] = _correct_column_ordering(
            report['tables'][0]['errors'],
            column_mapping
        )

    # If table was transposed for validation, reverse the transposition
    if schema.get("transpose"):
        report = _correct_transposition(report)

    # The UniquenessConstraint gives misleading errors
    # If a primary key value from the first row
    if schema.get("primaryKey"):
        _remove_misleading_uniqueness_errors(report, schema)

    # FIXME: Not clear on why I have to add the row back in to the report here
    def get_row(x):
        try:
            x['row'] = list(original_df.iloc[x['row-number']-1].fillna(''))
        except (IndexError, KeyError):
            x['row'] = list(original_df.iloc[0].fillna(''))
            x['row-number'] = 1
        return x

    if report['table-count'] > 0:
        report['tables'][0]['errors'] = list(map(
            get_row,
            report['tables'][0]['errors']
        ))
        report['tables'][0]['headers'] = list(actual_headers.fillna(""))

        validation.status = u'success' if report[u'valid'] else u'failure'
        validation.report = report
    else:
        validation.status = u'error'
        validation.error = {
            'message': '\n'.join(report['warnings']) or _(u'No tables found')
        }

    validation.finished = datetime.datetime.utcnow()

    Session.add(validation)
    Session.commit()

    # Store result status in resource
    t.get_action('resource_patch')(
        {'ignore_auth': True,
         'user': t.get_action('get_site_user')({'ignore_auth': True})['name'],
         '_validation_performed': True},
        {'id': resource['id'],
         'validation_status': validation.status,
         'validation_timestamp': validation.finished.isoformat()})


def _load_dataframe(data, extension):

    # Read in table
    if extension == "csv":
        df = _read_csv_file(data, extension)
    elif extension in ["xls", "xlsx"]:
        df = _read_excel_file(data, extension)
    elif extension in ["shp"]:
        df = _read_shape_file(data)
    elif extension in ['json', 'geojson']:
        df = _read_json_file(data)
    else:
        raise t.ValidationError({
            _('Incorrect Extension'): [_('Cannot validate the file. Please check '
                                         'the file extension is correct.')]
        })
    df.columns = df.iloc[0]
    df.index = df[df.columns[0]]
    return df


def _read_csv_file(data, extension=None):
    try:
        return pandas.read_csv(open(data, 'rb'), header=None, index_col=None)
    except Exception as e:
        log.warning(e, exc_info=True)
        extension = "(" + extension + ")" if extension else ""
        raise t.ValidationError({
            _('Format'): [
                _('Could not read your CSV file. Are you sure your specified '
                  'format {} is correct?').format(extension)
            ]
        })


def _read_excel_file(data, extension=None):
    try:
        excel_file = pandas.ExcelFile(open(data, 'rb'))
        df = pandas.read_excel(excel_file, header=None, index_col=None)

    except Exception as e:
        log.warning(e, exc_info=True)
        extension = "(" + extension + ")" if extension else ""
        raise t.ValidationError({
            _('Format'): [
                _('Could not read your Excel file. Are you sure your specified '
                  'format {} is correct?').format(extension)
            ]
        })

    # Can only validate excel files with one worksheet.
    if len(excel_file.sheet_names) != 1:
        raise t.ValidationError({
            _('Multiple Worksheets'): [_('Your Excel file must contain only '
                                         'one worksheet for validation.')]
        })

    return df


def _read_json_file(json_path):
    """
    Reads a json or geojson file in as a pandas dataframe ready for validation.
    """
    # Load as plain JSON
    try:
        with open(json_path, 'r') as read_file:
            geojson = json.load(read_file)
    except Exception as e:
        log.exception(e)
        raise t.ValidationError({
            'JSON': [_(u'Unable to import JSON: ') + str(e)]
        })

    # Structure the data
    try:
        def create_row(feature):
            row = OrderedDict(feature['properties'])
            row['adr_geometry_check'] = bool(feature['geometry']['coordinates'])
            return row

        df_dict = map(create_row, geojson['features'])

    except Exception as e:
        log.exception(e)
        raise t.ValidationError({
            'JSON': [_(u'Unable to import JSON: ') + str(e)]
        })

    # Create the dataframe and insert the headers as the first row
    df = pandas.DataFrame(df_dict)
    cols = pandas.DataFrame([list(df.columns)], columns=list(df.columns))
    df = pandas.concat([cols, df], axis=0, ignore_index=True)

    return df


def _read_shape_file(shp_path):
    """
    Read a shapefile into a Pandas dataframe with a 'coords' column holding
    the geometry information. This uses the pyshp package.
    """
    try:
        zipped_file = zipfile.PyZipFile(shp_path)
        files = zipped_file.namelist()

    except Exception as e:
        log.exception(e)
        raise t.ValidationError({
            _('SHP File'): [_(u'Could not unzip file: ') + str(e)]
        })

    shp_files = filter(lambda v: '.shp' in v, files)
    if len(shp_files) != 1:
        raise t.ValidationError({
            _('SHP File'): [_(u'Zipped archive must contain exactly one .shp file.')]
        })

    try:
        myshp = zipped_file.open(shp_files[0])
        mydbf = zipped_file.open(shp_files[0][:-4]+'.dbf')
        myshx = zipped_file.open(shp_files[0][:-4]+'.shx')

        sf = shapefile.Reader(shp=myshp, dbf=mydbf, shx=myshx)
        fields = [x[0] for x in sf.fields][1:]
        records = [fields] + sf.records()
        df = pandas.DataFrame(data=records)

        def get_geometry(index):
            if index == 0:
                return 'adr_geometry_check'
            if index > 0:
                try:
                    return bool(sf.shapes()[index-1].points)
                except Exception as e:
                    log.debug("Failed to find geometry for index " +
                              str(index) + ":" + str(e))
                    return False

        df['adr_geometry_check'] = df.index.to_series().map(get_geometry)
        log.debug(df)

        return df

    except shapefile.ShapefileException as e:
        log.error(e)
        raise t.ValidationError({
            _('SHP File'): [_(u'Not a valid shp file: ') + str(e)]
        })


def _transpose_dataframe(df):
    # Transpose table
    if len(df.columns) == 0:
        transposed = df
    else:
        transposed = df.T
    return transposed


def _correct_transposition(report):
    report_string = json.dumps(report)
    report_string = re.sub(r'(column)(-| )', r'x987asdwn23l\2', report_string)
    report_string = re.sub(r'(Column)(-| )', r'x987asdwn23u\2', report_string)
    report_string = re.sub(r'(row)(-| )', r'column\2', report_string)
    report_string = re.sub(r'(Row)(-| )', r'Column\2', report_string)
    report_string = re.sub(r'x987asdwn23l', 'row', report_string)
    report_string = re.sub(r'x987asdwn23u', 'Row', report_string)
    return json.loads(report_string)


def _excel_string_io_wrapper(df):
    df = df.iloc[1:]  # Remove headers
    out = cStringIO.StringIO()
    df.to_excel(out, columns=None, index=None)
    out.seek(0)
    return out


def _validate_table(source, _format=u'csv', schema=None, **options):
    setup_custom_goodtables()
    report = validate(
        source,
        format=_format,
        schema=schema,
        **options
    )
    log.debug(u'Validating source: {}'.format(source))
    return report


def _get_site_user_api_key():
    site_user_name = t.get_action('get_site_user')({'ignore_auth': True}, {})
    site_user = t.get_action('get_site_user')(
        {'ignore_auth': True}, {'id': site_user_name})
    return site_user['apikey']


def _remove_na(na_value, df):
    return df.replace(na_value, pandas.np.NaN)


def _prep_foreign_keys(package, table_schema, resource, df):
    foreign_keys = {}

    for key in table_schema.get('foreignKeys', {}):

        log.debug("Prepping Foreign Key: " + str(key))

        resources = {v.get('schema', None): v for v in package['resources']}
        field = key['fields']
        reference = key['reference']['resource']
        reference_field = key['reference']['fields']
        form_field = 'foreign-key-' + field

        log.debug("Resource Keys: " + str(resource.keys()))
        log.debug("Form Field: " + str(form_field))

        if form_field in resource.keys() and not resource[form_field]:
            raise t.ValidationError({
                _('Required Foreign Key Configuration'): [_('Missing {} field').format(field)]
            })

        try:
            # An empty reference indicates another field in the same table
            # Far easier to get valid values from the table and insert here.
            if reference == "":
                foreign_keys[field] = list(df[reference_field].iloc[1:])
            # Fields in resource of form "foreign-key-<field>" store references
            # Insert these user-specified references into the schema
            elif form_field in resource.keys():
                foreign_keys[field] = resource[form_field] + ":" + reference_field
            # If no reference in form, check if reference is in same package
            elif reference in resources.keys():
                foreign_keys[field] = resources[reference]['id'] + ":" + reference_field
            # Default to some unique value identifying a reference not found error.
            else:
                foreign_keys[field] = "NOTFOUND:" + reference_field
        except Exception:
            foreign_keys[field] = "NOTFOUND:" + reference_field

    log.debug("Foreign keys: " + str(foreign_keys))

    # Write foreign key info to schema so it's available in goodtables check
    if foreign_keys:
        for field in table_schema['fields']:
            if field['name'] in foreign_keys.keys():
                field['foreignKey'] = foreign_keys[field['name']]


def _reorder_columns(schema, df):
    """
    Creating a preset in which you can configure whether the order of columns matters.
    """

    log.debug("Considering whether to switch column order")
    log.debug("Input dataframe column types: {}".format(df.dtypes))

    required_field_order = [x['name'] for x in schema.get('fields', [])]
    submitted_field_order = list(df.columns)

    errors = {}
    for field in set(required_field_order) - set(submitted_field_order):
        df[field] = pandas.np.NaN
        error_key = _("Missing {} column").format(field)
        error_message = (_("Uploaded data file is missing required "
                         "column \"{}\"").format(field))
        errors[error_key] = [error_message]

    if errors:
        raise t.ValidationError(errors)

    extra_columns = [x for x in submitted_field_order if x not in set(required_field_order)]
    new_column_order = required_field_order + extra_columns
    old_column_order = list(df.columns)
    column_mapping = {}

    log.debug("New Order: " + str(new_column_order))
    log.debug("Old Order: " + str(old_column_order))

    if new_column_order != old_column_order:
        log.debug("Switching column order")
        df = df[new_column_order]
        log.debug(
            'The fields have had to be reordered to pass validation. '
            'Column numbers in error messages may be wrong!'
        )
        for i, col in enumerate(new_column_order):
            column_mapping[i+1] = old_column_order.index(col) + 1
        log.debug("Column Number Mapping: " + str(column_mapping))

    log.debug("Reordered data frame: {}".format(df))
    return df, column_mapping


def _correct_column_ordering(errors, column_mapping):

    def correct_columns(x):
        new_col = column_mapping[x['column-number']]
        x['column-number'] = new_col
        x['message'] = re.sub(
            r'(olumn)( |-)([0-9]*)',
            'olumn {}'.format(new_col),
            x.get('message', '')
        )
        return x
    log.debug("Fixing Column Order For Errors : {}".format(
        errors
    ))
    return list(map(correct_columns, errors))


def _remove_misleading_uniqueness_errors(report, schema):
    for table in report['tables']:
        primary_key = schema.get("primaryKey", [])
        headers = table['headers']
        errors = table['errors']
        required_errors = [
            e for e in errors if e['code'] == 'required-constraint'
        ]
        primary_key_column_numbers = []

        for key in primary_key:
            try:
                primary_key_column_numbers.append(headers.index(key)+1)
            except ValueError:
                pass

        for error in required_errors:
            if error['column-number'] in primary_key_column_numbers:
                filtered_errors = [
                    e for e in errors if e['code'] != 'unique-constraint'
                ]
                table['errors'] = filtered_errors
                break

    return report
