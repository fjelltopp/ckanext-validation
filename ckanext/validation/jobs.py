# encoding: utf-8

import logging
import datetime
import json
import re

import requests
from sqlalchemy.orm.exc import NoResultFound
from frictionless import system, Resource, Package, Report, Schema, Dialect, Check, Checklist, Detector

from ckan.model import Session
import ckan.lib.uploader as uploader

import ckantoolkit as t
from ckan.plugins import core

from ckanext.scheming.helpers import scheming_get_dataset_schema

from ckanext.validation.model import Validation
from ckanext.validation.utils import get_update_mode_from_config


log = logging.getLogger(__name__)

# Module-level cache for the site user's JWT. Populated on the first call to
# _get_site_user_api_key() in a given worker process, and reused forever after
# so we don't mint a fresh admin token on every validation run.
_cached_site_user_token = None


def run_validation_job(resource):

    log.debug('Validating resource %s', resource['id'])

    try:
        validation = Session.query(Validation).filter(
            Validation.resource_id == resource['id']).one()
    except NoResultFound:
        validation = None

    if not validation:
        validation = Validation(resource_id=resource['id'])

    validation.status = 'running'
    Session.add(validation)
    Session.commit()

    # Update resource extras to show "running" status in UI. Only meaningful
    # in async mode — in sync mode the request blocks until validation
    # finishes, so the UI never observes an intermediate "running" state, and
    # the patch would re-enter the chained sync resource_update path.
    if get_update_mode_from_config() != 'sync':
        patch_context = {
            'ignore_auth': True,
            'user': t.get_action('get_site_user')({'ignore_auth': True})['name'],
            '_validation_performed': True
        }
        try:
            t.get_action('resource_patch')(patch_context, {
                'id': resource['id'],
                'validation_status': 'running',
            })
        except Exception as e:
            log.warning('Failed to set running status on resource: %s', str(e))

    options = t.config.get(
        'ckanext.validation.default_validation_options')
    if options:
        options = json.loads(options)
    else:
        options = {}

    resource_options = resource.get('validation_options')
    if resource_options and isinstance(resource_options, str):
        resource_options = json.loads(resource_options)
    if resource_options:
        options.update(resource_options)

    dataset = t.get_action('package_show')(
        {'ignore_auth': True}, {'id': resource['package_id']})

    source = None
    if resource.get('url_type') == 'upload':
        upload = uploader.get_resource_uploader(resource)
        if isinstance(upload, uploader.ResourceUpload) and not core.plugin_loaded('blob_storage'):
            source = upload.get_path(resource['id'])
        else:
            # Upload is not the default implementation (ie it's a cloud storage
            # implementation)
            pass_auth_header = t.asbool(
                t.config.get('ckanext.validation.pass_auth_header', True))
            if pass_auth_header:
                s = requests.Session()

                # SECURITY: resource['url'] is editor-writable. If we blindly
                # attached the site-user JWT to every outbound request, an
                # editor could point the URL at their own host and harvest an
                # admin token from the Authorization header. Restrict the
                # header to requests that stay on our own CKAN site.
                site_url = t.config.get('ckan.site_url', '').rstrip('/')
                target = resource.get('url', '')
                if site_url and target.startswith(site_url):
                    s.headers.update({
                        'Authorization': t.config.get(
                            'ckanext.validation.pass_auth_header_value',
                            _get_site_user_api_key())
                    })

                options['http_session'] = s

    if not source:
        source = resource['url']

    schema = resource.get('schema')

    if schema:
        if isinstance(schema, str):
            if schema.startswith('http'):
                r = requests.get(schema)
                schema = r.json()
            else:
                # Try to parse as JSON schema object
                try:
                    schema = json.loads(schema)
                except Exception as e:
                    # If it's not valid JSON, treat it as a schema identifier/reference
                    # and skip it (let frictionless auto-detect the schema)
                    log.debug('Schema field contains identifier "{}", skipping and using auto-detection: {}'.format(schema, str(e)))
                    schema = None

    _format = resource['format'].lower()

    reference_resources=[]
    foreign_keys_error = {}
    if schema and 'foreignKeys' in schema:
        try:
            reference_resources = _prepare_foreign_keys(dataset, schema)
        except Exception as e:
            foreign_keys_error = {'errors': 'Error preparing foreign keys: ' + str(e)}

    report = _validate_table(source, reference_resources=reference_resources, _format=_format, schema=schema, **options)

    # Hide uploaded files
    if type(report) == Report:
        report = report.to_dict()

    if 'tasks' in report:
        for table in report['tasks']:
            if table['place'].startswith('/'):
                table['place'] = resource['url']
    if 'warnings' in report:
        validation.status = 'error'
        for index, warning in enumerate(report['warnings']):
            report['warnings'][index] = re.sub(r'Table ".*"', 'Table', warning)
    if 'valid' in report:
        validation.status = 'success' if report['valid'] else 'failure'
        validation.report = json.dumps(report)
    else:
        validation.report = json.dumps(report)
        if 'errors' in report and report['errors']: 
            validation.status = 'error'
            validation.error = {
                'message': [str(err) for err in report['errors']]}
        else:
            validation.error = {'message': ['Errors validating the data']}
    validation.finished = datetime.datetime.utcnow()

    Session.add(validation)
    Session.commit()

    # Store result status in resource
    data_dict = {
        'id': resource['id'],
        'validation_status': validation.status,
        'validation_timestamp': validation.finished.isoformat(),
    }

    if get_update_mode_from_config() == 'sync':
        data_dict['_skip_next_validation'] = True,

    patch_context = {
        'ignore_auth': True,
        'user': t.get_action('get_site_user')({'ignore_auth': True})['name'],
        '_validation_performed': True
    }
    t.get_action('resource_patch')(patch_context, data_dict)




def _validate_table(source, _format='csv', schema=None, reference_resources=[], **options):

    # This option is needed to allow Frictionless Framework to validate absolute paths
    frictionless_context = { 'trusted': True }
    http_session = options.pop('http_session', None) or requests.Session()
    use_proxy = 'ckan.download_proxy' in t.config

    if use_proxy:
        proxy = t.config.get('ckan.download_proxy')
        log.debug('Download resource for validation via proxy: %s', proxy)
        http_session.proxies.update({'http': proxy, 'https': proxy})

    frictionless_context['http_session'] = http_session
    try:
        resource_schema = Schema.from_descriptor(schema) if schema else None
    except Exception as e:
        raise t.ValidationError({'schema': 'Invalid schema: ' + str(schema) + " failed with error:" + str(e)})

    # Load the Resource Dialect as described in https://framework.frictionlessdata.io/docs/framework/dialect.html
    if 'dialect' in options:
        dialect = Dialect.from_descriptor(options['dialect'])
        options['dialect'] = dialect

    # Load the list of checks and parameters declaratively as in https://framework.frictionlessdata.io/docs/checks/table.html
    if 'checks' in options:
        checklist = Checklist(checks = [Check.from_descriptor(c) for c in options.pop('checks')])
    else:
        # Note that it's very important to initialise Checklist with NOTHING and not None if there are no checks declared
        checklist = Checklist()
    if 'pick_errors' in options:
        checklist.pick_errors = options.pop('pick_errors', None)
    if 'skip_errors' in options:
        checklist.skip_errors = options.pop('skip_errors', None)

    # remove limit_errors and limit_rows
    limit_errors = options.pop('limit_errors', None)
    limit_rows = options.pop('limit_rows', None)

    # handle schema_sync frictionless option that ignores header (column) ordering
    if 'schema_sync' in options:
        schema_sync = options.pop('schema_sync', False)
        options['detector'] = Detector(schema_sync=schema_sync)

    with system.use_context(**frictionless_context):
        # load source as frictionless Resource
        if resource_schema:
            # with schema
            resource = Resource(path=source, format=_format, schema=resource_schema, **options)
        else:
            # without schema
            resource = Resource(path=source, format=_format, **options)

        # add resource to a frictionless Package
        package = Package(resources=[resource])

        # if foreign keys are defined, we need to add the referenced resource(s) to the package
        for reference in reference_resources:
            referenced_resource = Resource(**reference)
            package.add_resource(referenced_resource)

        # report = validate(package, pick_errors=pick_errors, skip_errors=skip_errors, limit_errors=limit_errors)
        report = package.validate(checklist=checklist, limit_errors=limit_errors, limit_rows=limit_rows)

    return report


def _load_if_json(value):
    try:
        json_object = json.loads(value)
    except ValueError as e:
        return None
    return json_object

def _prepare_foreign_keys(dataset, schema):
    referenced_resources = []

    for foreign_key in schema.get('foreignKeys', {}):
        log.debug(f'Prepping Foreign Key resources: {foreign_key}')

        if foreign_key['reference']['resource'] == '':
            continue

        foreign_key_resource = None
        foreign_key_format = 'json'
        if foreign_key['reference']['resource'].startswith('http'):
            log.debug(f"Foreign Key resource is at url: {foreign_key['reference']['resource']}")

            foreign_key_resource = foreign_key['reference']['resource']
        if json_object := _load_if_json(foreign_key['reference']['resource']):
            log.debug(f'Foreign Key resource is a json object with keys: {json_object.keys()}')

            foreign_key_resource = json_object
        else:
            log.debug('Foreign Key resource is (presumably) a resource in this dataset.')

            # get the available resources in this dataset
            dataset_resources = {_validation_get_schema(dataset['type'], r.get('resource_type')): {'url':r.get('url'), 'format': r.get('format')} for r in dataset['resources']}

            # check foreign key resource is in the dataset and get the url
            # if it turns out it isn't we will raise an exception
            if foreign_key['reference']['resource'] in dataset_resources.keys():
                foreign_key_resource = dataset_resources[foreign_key['reference']['resource']]['url']
                foreign_key_format = dataset_resources[foreign_key['reference']['resource']]['format'].lower()
            else:
                raise t.ValidationError(
                    {'foreignKey': 'Foreign key reference does not exist. ' +
                    'Must be a url, json object or a resource in this dataset but was: ' +
                    foreign_key['reference']['resource'] +
                    ' Available resources: ' + str(dataset_resources.keys()) +
                    ' Schema used: ' + str(schema)})
        
        referenced_resources.append({'name': foreign_key['reference']['resource'], 'path': foreign_key_resource, 'format': foreign_key_format})

    log.debug('Foreign key resources required: ' + str(referenced_resources))
    return referenced_resources

def _validation_get_schema(dataset_type, resource_type):
    schema = scheming_get_dataset_schema(dataset_type)
    for resource in schema.get('resources', []):
        if resource.get("resource_type", "") == resource_type:
            for field in resource.get('resource_fields', []):
                if field['field_name'] == "schema":
                    return field['field_value']

def _get_site_user_api_key():
    """
    Return a JWT for the site user. Cached per worker process; on first call
    any stale 'validation_internal' tokens are revoked so the api_token table
    doesn't accumulate one live admin token per validation run.
    """
    # Declare we're using the module-level cache variable (see top of file)
    # so the reassignment below updates the shared box, not a local copy.
    global _cached_site_user_token

    # Fast path: already minted a token earlier in this process — reuse it.
    if _cached_site_user_token:
        return _cached_site_user_token

    site_user = t.get_action('get_site_user')({'ignore_auth': True}, {})
    try:
        # Sweep any leftover 'validation_internal' tokens (from prior worker
        # runs that predate this caching logic) so they don't stay live.
        existing = t.get_action('api_token_list')(
            {'ignore_auth': True}, {'user': site_user['name']})
        for tok in existing:
            if tok.get('name') == 'validation_internal':
                t.get_action('api_token_revoke')(
                    {'ignore_auth': True}, {'jti': tok['id']})

        # Mint the one token we'll use for the lifetime of this process.
        token_data = t.get_action('api_token_create')(
            {'ignore_auth': True},
            {'user': site_user['name'], 'name': 'validation_internal'})
        _cached_site_user_token = token_data['token']
        return _cached_site_user_token
    except Exception:
        # Older CKAN without api_token_* actions — fall back to legacy apikey.
        return site_user.get('apikey', '')

