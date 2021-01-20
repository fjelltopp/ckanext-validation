# encoding: utf-8
import json
import os
from ckan.lib.helpers import url_for_static
from ckantoolkit import url_for, _, config, asbool, literal, get_action
from ckanext.scheming.helpers import scheming_get_dataset_schema
import logging
import requests
from ckanext.validation.custom_checks import get_spec_override

log = logging.getLogger(__name__)


def get_validation_badge(resource, in_listing=False):

    if in_listing and not asbool(
            config.get('ckanext.validation.show_badges_in_listings', True)):
        return ''

    if not resource.get('validation_status'):
        return ''

    messages = {
        'success': _('Valid data'),
        'failure': _('Invalid data'),
        'error': _('Error during validation'),
        'unknown': _('Data validation unknown'),
    }

    if resource['validation_status'] in ['success', 'failure', 'error']:
        status = resource['validation_status']
    else:
        status = 'unknown'

    validation_url = url_for(
        'validation_read',
        id=resource['package_id'],
        resource_id=resource['id'])

    badge_url = url_for_static(
        '/images/badges/data-{}-flat.svg'.format(status))

    return u'''
<a href="{validation_url}" class="validation-badge">
    <img src="{badge_url}" alt="{alt}" title="{title}"/>
</a>'''.format(
        validation_url=validation_url,
        badge_url=badge_url,
        alt=messages[status],
        title=resource.get('validation_timestamp', ''))


def validation_extract_report_from_errors(errors):

    report = None
    for error in errors.keys():
        if error.lower() == 'validation':
            report = errors[error]
            # Remove full path from table source
            source = report['tables'][0]['source']
            report['tables'][0]['source'] = source.split('/')[-1]
            msg = _('''
There are validation issues with this file, please see the
<a {params}>report</a> for details. Once you have resolved the issues,
click the button below to replace the file.''')
            params = [
                'href="#validation-report"',
                'data-module="modal-dialog"',
                'data-module-div="validation-report-dialog"',
            ]
            new_error = literal(msg.format(params=' '.join(params)))
            errors[error] = new_error
            break

    return report, errors


def show_validation_schemas():
    """ Returns a list of validation schemas"""
    schema_directory = config.get('ckanext.validation.schema_directory')
    if schema_directory:
        return _files_from_directory(schema_directory).keys()
    else:
        return []


def dump_json_value(value, indent=None):
    """
    Returns the object passed serialized as a JSON string.

    :param value: The object to serialize.
    :returns: The serialized object, or the original value if it could not be
        serialized.
    :rtype: string
    """
    try:
        return json.dumps(value, indent=indent, sort_keys=True)
    except (TypeError, ValueError):
        return value


def bootstrap_version():
    if config.get('ckan.base_public_folder') == 'public':
        return '3'
    else:
        return '2'


def validation_get_schema(dataset_type, resource_type):
    schema = scheming_get_dataset_schema(dataset_type)
    for resource in schema.get('resources', []):
        if resource.get("resource_type", "") == resource_type:
            for field in resource.get('resource_fields', []):
                if field['field_name'] == "schema":
                    return validation_load_json_schema(field['field_value'])


def validation_load_json_schema(schema):
    try:
        if schema.startswith('http'):
            r = requests.get(schema)
            return r.json()

        schema_filepath = get_schema_filepath(schema)
        if schema_filepath:
            with open(schema_filepath, 'rb') as schema_file:
                return json.load(schema_file)

        return json.loads(schema)

    # TODO: Except json.JSONDecodeError when upgrading to python 3
    except ValueError as e:
        log.error("Error loading schema: " + schema)
        log.exception(e)
        return None


def get_schema_filepath(schema):
    schema_directory = config['ckanext.validation.schema_directory']
    schemas = _files_from_directory(schema_directory)
    return schemas.get(schema)


def validation_get_foreign_keys(dataset_type, resource_type, pkg_name):
    log.debug(pkg_name)

    organization_id = get_action('package_show')(
        None,
        {'id': pkg_name}
    ).get('organization', {}).get('id')
    organization_extras = get_action('organization_show')(
        None,
        {'id': organization_id}
    ).get('extras', [])
    organization_extras = dict((d['key'], d['value']) for d in organization_extras)
    log.debug("Organisation Extras: {}".format(organization_extras))

    schema = validation_get_schema(dataset_type, resource_type)
    foreign_keys = schema.get('foreignKeys', [])
    foreign_key_options = {
        'fields': {},
        'expand_form': False
    }

    for key in foreign_keys:

        field = filter(lambda x: x['name'] == key['fields'], schema['fields'])[0]
        ref_options = []

        default_value = organization_extras.get('foreign-key-'+key['fields'])
        if not default_value:
            foreign_key_options['expand_form'] = True

        foreign_key_options['fields'][key['fields']] = {
            'field_name': key['fields'],
            'field_title': field['title'],
            'default_value': default_value,
            'options': ref_options
        }

    log.warning(foreign_key_options)
    return foreign_key_options


def _files_from_directory(path, extension='.json'):
    listed_files = {}
    for root, dirs, files in os.walk(path):
        for file in files:
            if extension in file:
                name = file.split(".json")[0]
                listed_files[name] = os.path.join(root, file)
    return listed_files


def validation_get_goodtables_spec():
    spec_override = get_spec_override()
    log.warning("Spec Override: {}".format(spec_override))
    return json.dumps(spec_override, sort_keys=True)
