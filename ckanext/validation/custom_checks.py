# encoding: utf-8
from six import string_types
from goodtables import Error
import ckantoolkit as t
from collections import namedtuple
import logging
from ckan.common import _
import goodtables.registry
from simpleeval import simple_eval, NameNotDefined

log = logging.getLogger(__name__)


class CustomConstraint(object):
    """
    Copied from the core good tables module to alter the behaviour slightly.
    We want to ignore rows where data does not exist.  The principle here is
    that the required constraint should be used to catch missing data, not the
    custom constraint.
    """

    def __init__(self, constraint, **options):
        self.__constraint = constraint

    def check_row(self, cells):
        # Prepare names
        names = {}
        for cell in cells:
            if None not in [cell.get('header'), cell.get('value')]:
                try:
                    names[cell['header']] = float(cell['value'])
                except ValueError:
                    pass

        # Check constraint
        try:
            # This call should be considered as a safe expression evaluation
            # https://github.com/danthedeckie/simpleeval
            assert simple_eval(self.__constraint, names=names)

        # ADR customisation of the upstream code simply catches NameNotDefined
        except NameNotDefined:
            return []

        except Exception:
            row_number = cells[0]['row-number']
            message = 'Custom constraint "{constraint}" fails for row {row_number}'
            message_substitutions = {
                'constraint': self.__constraint,
            }
            error = Error(
                'custom-constraint',
                row_number=row_number,
                message=message,
                message_substitutions=message_substitutions
            )
            return [error]


def enumerable_constraint(cells):
    errors = []

    for cell in cells:
        field = cell.get('field')
        value = cell.get('value')

        # Skip if cell has no field
        if field is None:
            continue

        # Check constraint
        valid = field.test_value(value, constraints=['enum'])

        # Add error
        if not valid:
            message_substitutions = {
                'value': u'"{}"'.format(value),
                'constraint': u'"{}"'.format('", "'.join(field.constraints['enum']))
            }
            error = Error(
                'enumerable-constraint',
                cell,
                message_substitutions=message_substitutions
            )
            errors.append(error)
    return errors


class UniqueConstraint(object):
    """
    We create a copy of the GoodTables uniqueness check so that we can
    issue a more specific error message whe composite uniqueness check fails.
    """

    def __init__(self, **options):
        self.__unique_fields_cache = None
        self.__primary_key_fields = None

    def check_row(self, cells):
        log.debug('Checking unique constraint')
        errors = []

        # Prepare unique checks
        if self.__unique_fields_cache is None:
            self._create_unique_fields_cache(cells)

        # Check unique
        for column_numbers, cache in self.__unique_fields_cache.items():
            column_cells = tuple(
                cell
                for column_number, cell in enumerate(cells, start=1)
                if column_number in column_numbers
            )
            column_values = tuple(cell.get('value') for cell in column_cells)
            row_number = column_cells[0]['row-number']

            all_values_are_none = (set(column_values) == {None})
            if not all_values_are_none:
                if column_values in cache['data']:
                    # Custom code =============================================
                    message_substitutions = {
                        'row_numbers': str(row_number),
                        'primary_key_fields': ', '.join(self.__primary_key_fields)
                    }
                    if len(column_numbers) == 1:
                        error = Error(
                            'unique-constraint',
                            column_cells[0],
                            message_substitutions=message_substitutions
                        )
                    else:
                        error = Error(
                            'unique-constraint',
                            column_cells[0],
                            message="Rows {row_numbers} have a composite uniqueness constraint violation."
                                    " Primary key fields ({primary_key_fields}) must form a unique combination"
                                    " in the dataset.",
                            message_substitutions=message_substitutions
                        )
                    # End Custom code =========================================
                    errors.append(error)
                cache['data'].add(column_values)
                cache['refs'].append(row_number)

        return errors

    def _create_unique_fields_cache(self, cells):
        primary_key_column_numbers = []
        primary_key_fields = []
        cache = {}

        # Unique
        for column_number, cell in enumerate(cells, start=1):
            field = cell.get('field')
            if field is not None:
                if field.descriptor.get('primaryKey'):
                    primary_key_column_numbers.append(column_number)
                    primary_key_fields.append(field.descriptor.get('name'))
                if field.constraints.get('unique'):
                    cache[tuple([column_number])] = {
                        'data': set(),
                        'refs': [],
                    }

        # Primary key
        if primary_key_column_numbers:
            cache[tuple(primary_key_column_numbers)] = {
                'data': set(),
                'refs': [],
            }

        self.__unique_fields_cache = cache
        self.__primary_key_fields = primary_key_fields


def geometry_check(cells):
    """
    Certain file types come with built in geometry e.g. SHP and GeoJSON. For
    these file types we prepare them with an adr_geometry_exists column, and
    here require that column to be truthy if the file is to pass validation.  This
    """
    log.debug('Geometry Check Called')

    for cell in cells:
        # Only run check if an adr_geometry_exists column in data
        if cell['header'] == 'adr_geometry_check':
            # If the geometry is falsy (including strings "False") then error
            if not cell['value'] or (cell['value'] in ["False", "false"]):
                log.debug('Missing geometry in row ' + str(cell['row-number']))
                return [Error(
                    'missing-geometry',
                    None,
                    row_number=cell['row-number']
                )]
            # If geometry exists
            else:
                log.debug('Found geometry in cell: ' +
                          str(cell) + " - " + str(cell['value']))
                return []
    else:
        log.debug("No geometry in this dataset")
        return []


class ForeignKeyCheck(object):

    def __init__(self, **options):
        self.__foreign_fields_cache = None
        self._missing_ref = {}

    def check_row(self, cells):
        log.debug("Checking foreign keys")
        # Prepare cache
        if self.__foreign_fields_cache is None:
            self.__foreign_fields_cache = \
                ForeignKeyCheck._create_foreign_fields_cache(cells)
            log.debug("The Foreign Fields Cache:")
            log.debug(self.__foreign_fields_cache)

        # Step through the cells and check values are valid
        errors = []
        for cell in cells:

            default_field = namedtuple('field', 'descriptor')
            field = cell.get('field', default_field(descriptor={}))

            if field.descriptor.get('foreignKey'):

                if not self.__foreign_fields_cache.get(cell['header']):
                    self.__foreign_fields_cache = merge_two_dicts(
                        self.__foreign_fields_cache,
                        ForeignKeyCheck._create_foreign_fields_cache([cell])
                    )

                cell_cache = self.__foreign_fields_cache.get(cell['header'])
                valid_values = cell_cache.get('values', [])
                resource_id = cell_cache.get('resource_id', "")
                resource_url = cell_cache.get('resource_url', "")

                # Check if ref resource missing, so we only return one error
                missing = self._missing_ref.get(field.descriptor.get('name'))

                if not valid_values and cell['row-number'] <= 2:
                    errors.append(Error(
                        'foreign-key',
                        cell,
                        row_number=cell['row-number'],
                        message=_("No foreign-key reference found. "
                                  "Does the referenced resource exist?")
                    ))
                    self._missing_ref[field.descriptor.get('name')] = True

                elif str(cell['value']) not in valid_values and not missing:
                    errors.append(Error(
                        'foreign-key',
                        cell,
                        row_number=cell['row-number'],
                        message_substitutions={
                            'resource_id': resource_id,
                            'resource_url': resource_url
                        },
                        message=_("Area ID in column {column_number} and row "
                                  "{row_number} is not found in the "
                                  "referenced geographic hierachy (resource id: {resource_id})")
                    ))

        return errors

    @staticmethod
    def _create_foreign_fields_cache(cells):

        log.debug("Creating foreign key cache")
        cache = {}

        for column_number, cell in enumerate(cells, start=1):

            log.debug("Cell: {}".format(cell))
            default_field = namedtuple('field', 'descriptor')
            field = cell.get('field', default_field(descriptor={}))
            foreign_key = field.descriptor.get('foreignKey')

            if foreign_key:

                # Default to empty values if resource not found/specfied
                res_id = ""
                values = []

                # If field is a string, then it is a resource reference
                if isinstance(foreign_key, string_types):
                    try:
                        res_id, field = tuple(foreign_key.split(':')[0:2])
                        log.debug("Getting valid foreign key values")
                        values = ForeignKeyCheck._get_valid_values(
                            res_id,
                            field
                        )
                    except t.ObjectNotFound:
                        pass

                # If field is a list, then the valid values already determined
                elif type(foreign_key) is list:
                    res_id = ""
                    values = foreign_key

                cache[cell['header']] = {
                    'values': values,
                    'resource_id': res_id
                }

        log.debug("Foreign Key cache: {}".format(cache))
        return cache

    @staticmethod
    def _get_valid_values(resource_id, field):
        data_dict = {
            'resource_id': resource_id,
            'fields': [field],
            'limit': 3000
        }
        register_translator()
        result = t.get_action('datastore_search')(
            # FIXME: Should we really ignore the auth here?
            {'ignore_auth': True},
            data_dict
        )
        log.debug("Got valid values: {}".format(result))
        valid_values = [str(x[field]) for x in result.get('records', [])]
        return valid_values


def register_translator():
    # Workaround until core translation function defaults to Flask
    from paste.registry import Registry
    from ckan.lib.cli import MockTranslator
    from pylons import translator
    registry = Registry()
    registry.prepare()
    registry.register(translator, MockTranslator())


def merge_two_dicts(x, y):
    z = x.copy()  # start with x's keys and values
    z.update(y)  # modifies z with y's keys and values & returns None
    return z


def setup_custom_goodtables():
    # Override the goodtables spec to include translation and custom errors
    goodtables.registry.spec = get_spec_override()

    # Register custom checks here.
    goodtables.registry.registry.register_check(
        ForeignKeyCheck, 'foreign-key', None, None, None
    )
    goodtables.registry.registry.register_check(
        geometry_check, 'missing-geometry', None, None, None
    )
    goodtables.registry.registry.register_check(
        UniqueConstraint, 'unique-constraint', None, None, None
    )
    goodtables.registry.registry.register_check(
        enumerable_constraint, 'enumerable-constraint', None, None, None
    )
    goodtables.registry.registry.register_check(
        CustomConstraint, 'custom-constraint', type='custom', context='body'
    )


def get_spec_override():
    return {
        "version": "1.0.0",
        "errors": {
            "io-error": {
                "name": _("IO Error"),
                "type": "source",
                "context": "table",
                "weight": 100,
                "message": _('The data source returned an IO Error of type {error_type}'),
                "description": _("Data reading error because of IO error.\n\n"
                                 " How it could be resolved:\n - Fix path if it\'s not correct.")
            },
            "http-error": {
                "name": _("HTTP Error"),
                "type": "source",
                "context": "table",
                "weight": 100,
                "message": _("The data source returned an HTTP error with a status code of {status_code}"),
                "description": _("Data reading error because of HTTP error.\n\n How it could be resolved:\n"
                                 " - Fix url link if it's not correct."),
            },
            "source-error": {
                "name": _("Source Error"),
                "type": "source",
                "context": "table",
                "weight": 100,
                "message": _("The data source has not supported or has inconsistent contents;"
                             " no tabular data can be extracted"),
                "description": _("Data reading error because of not supported or inconsistent contents.\n\n"
                                 " How it could be resolved:\n"
                                 " - Fix data contents (e.g. change JSON data to array or arrays/objects).\n"
                                 " - Set correct source settings in {validator}."),
            },
            "scheme-error": {
                "name": _("Scheme Error"),
                "type": "source",
                "context": "table",
                "weight": 100,
                "message": _("The data source is in an unknown scheme; no tabular data can be extracted"),
                "description": _("Data reading error because of incorrect scheme.\n\n How it could be resolved:\n"
                                 " - Fix data scheme (e.g. change scheme from `ftp` to `http`).\n"
                                 " - Set correct scheme in {validator}."),
            },
            "format-error": {
                "name": _("Format Error"),
                "type": "source",
                "context": "table",
                "weight": 100,
                "message": _("The data source is in an unknown format; no tabular data can be extracted"),
                "description": _("Data reading error because of incorrect format.\n\n How it could be resolved:\n"
                                 " - Fix data format (e.g. change file extension from `txt` to `csv`).\n"
                                 " - Set correct format in {validator}."),
            },
            "encoding-error": {
                "name": _("Encoding Error"),
                "type": "source",
                "context": "table",
                "weight": 100,
                "message": _("The data source could not be successfully decoded with {encoding} encoding"),
                "description": _("Data reading error because of an encoding problem.\n\n How it could be resolved:\n"
                                 " - Fix data source if it's broken.\n - Set correct encoding in {validator}."),
            },
            "blank-header": {
                "name": _("Blank Header"),
                "type": "structure",
                "context": "head",
                "weight": 3,
                "message": _("Header in column {column_number} is blank"),
                "description": _("A column in the header row is missing a value. Column names should be provided.\n\n"
                                 " How it could be resolved:\n"
                                 " - Add the missing column name to the first row of the data source.\n"
                                 " - If the first row starts with, or ends with a comma, remove it.\n"
                                 " - If this error should be ignored disable `blank-header` check in {validator}."),
            },
            "duplicate-header": {
                "name": _("Duplicate Header"),
                "type": "structure",
                "context": "head",
                "weight": 3,
                "message": _("Header in column {column_number} is duplicated to header in column(s) {column_numbers}"),
                "description": _("Two columns in the header row have the same value. Column names should be unique.\n\n"
                                 " How it could be resolved:\n"
                                 " - Add the missing column name to the first row of the data.\n"
                                 " - If the first row starts with, or ends with a comma, remove it.\n"
                                 " - If this error should be ignored disable `duplicate-header` check in {validator}."),
            },
            "blank-row": {
                "name": _("Blank Row"),
                "type": "structure",
                "context": "body",
                "weight": 9,
                "message": _("Row {row_number} is completely blank"),
                "description": _("This row is empty. A row should contain at least one value.\n\n"
                                 " How it could be resolved:\n - Delete the row.\n"
                                 " - If this error should be ignored disable `blank-row` check in {validator}."),
            },
            "duplicate-row": {
                "name": _("Duplicate Row"),
                "type": "structure",
                "context": "body",
                "weight": 5,
                "message": _("Row {row_number} is duplicated to row(s) {row_numbers}"),
                "description": _("The exact same data has been seen in another row.\n\n"
                                 " How it could be resolved:\n"
                                 " - If some of the data is incorrect, correct it.\n"
                                 " - If the whole row is an incorrect duplicate, remove it.\n"
                                 " - If this error should be ignored disable `duplicate-row` check in {validator}."),
            },
            "extra-value": {
                "name": _("Extra Value"),
                "type": "structure",
                "context": "body",
                "weight": 9,
                "message": _("Row {row_number} has an extra value in column {column_number}"),
                "description": _("This row has more values compared to the header row (the first row in the data source)."
                                 " A key concept is that all the rows in tabular data must have the same number of"
                                 " columns.\n\n"
                                 " How it could be resolved:\n"
                                 " - Check data has an extra comma between the values in this row.\n"
                                 " - If this error should be ignored disable `extra-value` check in {validator}."),
            },
            "missing-value": {
                "name": _("Missing Value"),
                "type": "structure",
                "context": "body",
                "weight": 9,
                "message": _("Row {row_number} has a missing value in column {column_number}"),
                "description": _("This row has less values compared to the header row (the first row in the data source)."
                                 " A key concept is that all the rows in tabular data must have the same number"
                                 " of columns.\n\n"
                                 " How it could be resolved:\n"
                                 " - Check data is not missing a comma between the values in this row.\n"
                                 " - If this error should be ignored disable `missing-value` check in {validator}."),
            },
            "schema-error": {
                "name": _("Table Schema Error"),
                "type": "schema",
                "context": "table",
                "weight": 15,
                "message": _("Table Schema error: {error_message}"),
                "description": _("Provided schema is not valid.\n\n How it could be resolved:\n"
                                 " - Update schema descriptor to be a valid descriptor\n"
                                 " - If this error should be ignored disable schema checks in {validator}."),
            },
            "non-matching-header": {
                "name": _("Non-Matching Header"),
                "type": "schema",
                "context": "head",
                "weight": 9,
                "message": _("Header in column {column_number} doesn't match field name {field_name} in the schema"),
                "description": _("One of the data source headers doesn't match the field name defined in the schema.\n\n"
                                 " How it could be resolved:\n - Rename header in the data source or field in the schema\n"
                                 " - If this error should be ignored disable `non-matching-header` check in {validator}."),
            },
            "extra-header": {
                "name": _("Extra Header"),
                "type": "schema",
                "context": "head",
                "weight": 9,
                "message": _("There is an extra header in column {column_number}"),
                "description": _("The first row of the data source contains header that doesn't exist in the schema.\n\n"
                                 " How it could be resolved:\n"
                                 " - Remove the extra column from the data source or add the missing field to the schema\n"
                                 " - If this error should be ignored disable `extra-header` check in {validator}."),
            },
            "missing-header": {
                "name": _("Missing Header"),
                "type": "schema",
                "context": "head",
                "weight": 9,
                "message": _("There is a missing header in column {column_number}"),
                "description": _("Based on the schema there should be a header that is missing in the first row of"
                                 " the data source.\n\n How it could be resolved:\n"
                                 " - Add the missing column to the data source or remove the extra field from the schema\n"
                                 " - If this error should be ignored disable `missing-header` check in {validator}."),
            },
            "type-or-format-error": {
                "name": _("Type or Format Error"),
                "type": "schema",
                "context": "body",
                "weight": 9,
                "message": _("The value {value} in row {row_number} and column {column_number} is not type {field_type} and"
                             " format {field_format}"),
                "description": _("The value does not match the schema type and format for this field.\n\n"
                                 " How it could be resolved:\n - If this value is not correct, update the value.\n"
                                 " - If this value is correct, adjust the type and/or format.\n"
                                 " - To ignore the error, disable the `type-or-format-error` check in {validator}."
                                 " In this case all schema checks for row values will be ignored."),
            },
            "required-constraint": {
                "name": _("Required Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 9,
                "message": _("Column {column_number} is a required field, but row {row_number} has no value"),
                "description": _("This field is a required field, but it contains no value.\n\n How it could be resolved:\n"
                                 " - If this value is not correct, update the value.\n"
                                 " - If value is correct, then remove the `required` constraint from the schema.\n"
                                 " - If this error should be ignored disable `required-constraint` check in {validator}."),
            },
            "pattern-constraint": {
                "name": _("Pattern Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _("The value {value} in row {row_number} and column {column_number} does not conform to the"
                             " pattern constraint of {constraint}"),
                "description": _("This field value should conform to constraint pattern.\n\n How it could be resolved:\n"
                                 " - If this value is not correct, update the value.\n"
                                 " - If value is correct, then remove or refine the `pattern` constraint in the schema.\n "
                                 "- If this error should be ignored disable `pattern-constraint` check in {validator}."),
            },
            "unique-constraint": {
                "name": _("Unique Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 9,
                "message": _("Rows {row_numbers} has unique constraint violation in column {column_number}"),
                "description": _("This field is a unique field but it contains a value that has been used"
                                 " in another row.\n\n"
                                 " How it could be resolved:\n - If this value is not correct, update the value.\n"
                                 " - If value is correct, then the values in this column are not unique."
                                 " Remove the `unique` constraint from the schema.\n"
                                 " - If this error should be ignored disable `unique-constraint` check in {validator}."),
            },
            "enumerable-constraint": {
                "name": _("Invalid Value"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _("The value {value} in row {row_number} and column {column_number} is not found in the list"
                             " of valid values for this field: {constraint}"),
                "description": _("This field value should be equal to one of the values in a pre-specified list.\n\n"
                                 "  Please update the value making sure it exactly matches one of the valid values in"
                                 " the specified list."),
            },
            "minimum-constraint": {
                "name": _("Minimum Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _("The value {value} in row {row_number} and column {column_number} does not conform to"
                             " the minimum constraint of {constraint}"),
                "description": _("This field value should be greater or equal than constraint value.\n\n"
                                 " How it could be resolved:\n - If this value is not correct, update the value.\n"
                                 " - If value is correct, then remove or refine the `minimum` constraint in the schema.\n"
                                 " - If this error should be ignored disable `minimum-constraint` check in {validator}."),
            },
            "maximum-constraint": {
                "name": _("Maximum Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _("The value {value} in row {row_number} and column {column_number} does not conform to"
                             " the maximum constraint of {constraint}"),
                "description": _("This field value should be less or equal than constraint value.\n\n"
                                 " How it could be resolved:\n - If this value is not correct, update the value.\n"
                                 " - If value is correct, then remove or refine the `maximum` constraint in the schema.\n"
                                 " - If this error should be ignored disable `maximum-constraint` check in {validator}."),
            },
            "minimum-length-constraint": {
                "name": _("Minimum Length Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _("The value {value} in row {row_number} and column {column_number} does not conform to"
                             " the minimum length constraint of {constraint}"),
                "description": _("A length of this field value should be greater or equal than schema constraint value.\n\n"
                                 " How it could be resolved:\n - If this value is not correct, update the value.\n"
                                 " - If value is correct, then remove or refine the `minimumLength` constraint"
                                 " in the schema.\n"
                                 " - If this error should be ignored disable `minimum-length-constraint` check"
                                 " in {validator}."),
            },
            "maximum-length-constraint": {
                "name": _("Maximum Length Constraint"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _(
                    "The value {value} in row {row_number} and column {column_number} does not conform to the maximum"
                    " length constraint of {constraint}"),
                "description": _(
                    "A length of this field value should be less or equal than schema constraint value.\n\n"
                    " How it could be resolved:\n"
                    " - If this value is not correct, update the value.\n"
                    " - If value is correct, then remove or refine the `maximumLength` constraint in the schema.\n"
                    " - If this error should be ignored disable `maximum-length-constraint` check in {validator}."),
            },
            "missing-geometry": {
                "name": _("Geometry Error"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _("There is no geometry specified for row {row_number}."),
                "description": _("Every record in a geometry file, must include geometry co-ordinates.")
            },
            "foreign-key": {
                "name": _("Area ID Error"),
                "type": "schema",
                "context": "body",
                "weight": 7,
                "message": _(
                    "Value in column {column_number} and row {row_number} is not found in the referenced"
                    " data table: {resource_id}"),
                "description": _(
                    "Area IDs must match those from the referenced location hierachy.  Please check the location hierachy.")
            }
        }
    }
