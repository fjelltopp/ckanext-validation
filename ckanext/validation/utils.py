import os
import logging
import cgi
import json

from werkzeug.datastructures import FileStorage as FlaskFileStorage
from ckan.lib.uploader import ResourceUpload
from ckantoolkit import config, asbool
import ckantoolkit as t


log = logging.getLogger(__name__)

ALLOWED_UPLOAD_TYPES = (cgi.FieldStorage, FlaskFileStorage)


def _get_underlying_file(wrapper):
    if isinstance(wrapper, FlaskFileStorage):
        return wrapper.stream
    return wrapper.file


def process_schema_fields(data_dict):
    u'''
    Normalize the different ways of providing the `schema` field

    1. If `schema_upload` is provided and it's a valid file, the contents
       are read into `schema`.
    2. If `schema_url` is provided and looks like a valid URL, it's copied
       to `schema`
    3. If `schema_json` is provided, it's copied to `schema`.

    All the 3 `schema_*` fields are removed from the data_dict.
    Note that the data_dict still needs to pass validation
    '''

    schema_upload = data_dict.pop(u'schema_upload', None)
    schema_url = data_dict.pop(u'schema_url', None)
    schema_json = data_dict.pop(u'schema_json', None)
    if isinstance(schema_upload, ALLOWED_UPLOAD_TYPES):
        uploaded_file = _get_underlying_file(schema_upload)
        data_dict[u'schema'] = uploaded_file.read()
        if isinstance(data_dict["schema"], (bytes, bytearray)):
            data_dict["schema"] = data_dict["schema"].decode()
    elif schema_url:

        if (not isinstance(schema_url, str) or
                not schema_url.lower()[:4] == u'http'):
            raise t.ValidationError({u'schema_url': 'Must be a valid URL'})
        data_dict[u'schema'] = schema_url
    elif schema_json:
        data_dict[u'schema'] = schema_json

    return data_dict


def get_update_mode_from_config():
    if asbool(
            config.get(u'ckanext.validation.run_on_update_sync', False)):
        return u'sync'
    elif asbool(
            config.get(u'ckanext.validation.run_on_update_async', True)):
        return u'async'
    else:
        return None


def get_create_mode_from_config():
    if asbool(
            config.get(u'ckanext.validation.run_on_create_sync', False)):
        return u'sync'
    elif asbool(
            config.get(u'ckanext.validation.run_on_create_async', True)):
        return u'async'
    else:
        return None


def get_local_upload_path(resource_id):
    u'''
    Returns the local path to an uploaded file give an id

    Note: it does not check if the resource or file actually exists
    '''
    upload = ResourceUpload({u'url': u'foo'})
    return upload.get_path(resource_id)


def delete_local_uploaded_file(resource_id):
    u'''
    Remove and uploaded file and its parent folders (if empty)

    This assumes the default folder structure of:

        {ckan.storage_path}/resources/{uuid[0:3]}/{uuid[3:6}/{uuid[6:]}

    Note: some checks are performed in case a custom uploader class is used,
    but is not guaranteed to work in all circumstances. Please test before!
    '''
    path = get_local_upload_path(resource_id)

    try:
        if os.path.exists(path):
            os.remove(path)

        first_directory = os.path.split(path)[0]
        if first_directory.endswith(u'resources'):
            return
        if os.listdir(first_directory) == []:
            os.rmdir(first_directory)

        second_directory = os.path.split(first_directory)[0]
        if second_directory.endswith(u'resources'):
            return
        if os.listdir(second_directory) == []:
            os.rmdir(second_directory)

    except OSError as e:
        log.warning(u'Error deleting uploaded file: %s', e)
