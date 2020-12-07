import json
import io
import mock
import datetime
import pytest

import ckan.model as model
import ckanext.validation.model as vmodel

from nose.tools import assert_in, assert_equals

from ckan.tests.factories import Sysadmin, Dataset, Resource
from ckan.tests.helpers import call_action, reset_db
from ckan.lib.helpers import url_for

from ckanext.validation.model import create_tables, tables_exist
from ckanext.validation.tests.helpers import (
    VALID_CSV, INVALID_CSV, mock_uploads
)

from bs4 import BeautifulSoup

PLUGIN_CONTROLLER = 'ckanext.validation.controller:ValidationController'

@pytest.fixture
def initdb():
    model.Session.remove()
    model.Session.configure(bind=model.meta.engine)
    if not vmodel.tables_exist():
        vmodel.create_tables()

def _get_resource_new_page_as_sysadmin(app, id):
    user = Sysadmin()
    env = {'REMOTE_USER': user['name'].encode('ascii')}
    response = app.get(
        url='/dataset/new_resource/{}'.format(id),
        extra_environ=env,
    )
    return env, response


def _get_resource_update_page_as_sysadmin(app, id, resource_id):
    user = Sysadmin()
    env = {'REMOTE_USER': user['name'].encode('ascii')}
    response = app.get(
        url='/dataset/{}/resource_edit/{}'.format(id, resource_id),
        extra_environ=env,
    )
    return env, response

@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
@pytest.mark.ckan_config(u'ckan.plugins', u'validation')
@pytest.mark.usefixtures(u'with_plugins')
class TestResourceSchemaForm(object):


    def test_resource_form_includes_json_fields(self, app):
        dataset = Dataset()

        env, response = _get_resource_new_page_as_sysadmin(app, dataset['id'])

        html = BeautifulSoup(response.body)

        form = response.forms['resource-edit']
        assert_in('schema', form.fields)
        assert_equals(form.fields['schema'][0].tag, 'input')
        assert_equals(form.fields['schema_json'][0].tag, 'textarea')
        assert_equals(form.fields['schema_url'][0].tag, 'input')

    def test_resource_form_create(self, app):
        dataset = Dataset()
        user = Sysadmin()
        env = {'REMOTE_USER': user['name'].encode('ascii')}

        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        json_value = json.dumps(value)

        app.post(
            url_for(
                "{}_resource.new".format(dataset["type"]), id=dataset["id"]
            ),
            extra_environ=env,
            data={
                "url": "https://example.com/data.csv",
                "schema": json_value,
                "save": "go-dataset-complete",
                "id": ""
            }
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(json.loads(dataset['resources'][0]['schema']), value)

    def test_resource_form_create_json(self, app):
        dataset = Dataset()
        user = Sysadmin()
        env = {'REMOTE_USER': user['name'].encode('ascii')}

        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        json_value = json.dumps(value)

        app.post(
            url_for(
                "{}_resource.new".format(dataset["type"]), id=dataset["id"]
            ),
            extra_environ=env,
            data={
                "url": "https://example.com/data.csv",
                "schema_json": json_value,
                "save": "go-dataset-complete",
                "id": ""
            }
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(json.loads(dataset['resources'][0]['schema']), value)

    def test_resource_form_create_upload(self, app):
        dataset = Dataset()
        user = Sysadmin()
        env = {'REMOTE_USER': user['name'].encode('ascii')}

        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        json_value = json.dumps(value)

        upload = ('schema_upload', 'schema.json', json_value)

        app.post(
            url_for(
                "{}_resource.new".format(dataset["type"]), id=dataset["id"]
            ),
            extra_environ=env,
            data={
                "url": "https://example.com/data.csv",
                "schema_json": json_value,
                "save": "go-dataset-complete",
                "upload_files": [upload],
                "id": ""
            }
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['schema'], value)

    def test_resource_form_create_url(self, app):
        dataset = Dataset()
        user = Sysadmin()
        env = {'REMOTE_USER': user['name'].encode('ascii')}

        value = 'https://example.com/schemas.json'

        app.post(
            url_for(
                "{}_resource.new".format(dataset["type"]), id=dataset["id"]
            ),
            extra_environ=env,
            data={
                "url": "https://example.com/data.csv",
                "schema_json": value,
                "save": "go-dataset-complete",
                "id": ""
            }
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['schema'], value)

    def test_resource_form_update(self, app):
        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        dataset = Dataset()
        resource = Resource(
            package_id=dataset['id'],
            url='https://example.com/data.csv',
            schema=value
        )

        value = {
            "fields": [
                {"name": "code"},
                {"name": "department"},
                {"name": "date"}
            ]
        }

        call_action(
            "resource_patch",
            id=resource["id"],
            name="somethingnew",
            schema=value
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['schema'], value)

    def test_resource_form_update_json(self, app):

        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        dataset = Dataset()
        resource = Resource(
            package_id=dataset['id'],
            url='https://example.com/data.csv',
            schema=value
        )

        value = {
            "fields": [
                {"name": "code"},
                {"name": "department"},
                {"name": "date"}
            ]
        }

        json_value = json.dumps(value)

        call_action(
            "resource_update",
            id=resource["id"],
            name="somethingnew",
            schema_json=json_value
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['schema'], value)

    def test_resource_form_update_url(self, app):
        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        dataset = Dataset()
        resource = Resource(
            package_id=dataset['id'],
            url='https://example.com/data.csv',
            schema=value
        )

        value = 'https://example.com/schema.json'

        call_action(
            "resource_update",
            id=resource["id"],
            name="somethingnew",
            schema_url=value
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['schema'], value)

    def test_resource_form_update_upload(self, app):
        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'}
            ]
        }
        dataset = Dataset(
            resources=[{
                'url': 'https://example.com/data.csv',
                'schema': value
            }]
        )

        app = self._get_test_app()
        env, response = _get_resource_update_page_as_sysadmin(
            app, dataset['id'], dataset['resources'][0]['id'])
        form = response.forms['resource-edit']

        assert_equals(
            form['schema_json'].value, json.dumps(value, indent=2))

        value = {
            'fields': [
                {'name': 'code'},
                {'name': 'department'},
                {'name': 'date'}
            ]
        }

        json_value = json.dumps(value)

        upload = ('schema_upload', 'schema.json', json_value)
        form['url'] = 'https://example.com/data.csv'

        webtest_submit(
                form, 'save', upload_files=[upload], extra_environ=env)

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['schema'], value)

@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
class TestResourceValidationOptionsForm(object):

    def test_resource_form_includes_json_fields(self, app):
        dataset = Dataset()

        app = self._get_test_app()
        env, response = _get_resource_new_page_as_sysadmin(app, dataset['id'])
        form = response.forms['resource-edit']
        assert_in('validation_options', form.fields)
        assert_equals(form.fields['validation_options'][0].tag, 'textarea')

    def test_resource_form_create(self, app):

        dataset = Dataset()
        user = Sysadmin()
        env = {'REMOTE_USER': user['name'].encode('ascii')}

        value = {
            'delimiter': ';',
            'headers': 2,
            'skip_rows': ['#'],
        }
        json_value = json.dumps(value)

        app.post(
            url_for(
                "{}_resource.new".format(dataset["type"]), id=dataset["id"]
            ),
            extra_environ=env,
            data={
                "url": "https://example.com/data.csv",
                "validation_options": json_value,
                "save": "go-dataset-complete",
                "id": ""
            }
        )

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['validation_options'], value)

    def test_resource_form_update(self, app):
        value = {
            'delimiter': ';',
            'headers': 2,
            'skip_rows': ['#'],
        }

        dataset = Dataset(
            resources=[{
                'url': 'https://example.com/data.csv',
                'validation_options': value
            }]
        )

        app = self._get_test_app()
        env, response = _get_resource_update_page_as_sysadmin(
            app, dataset['id'], dataset['resources'][0]['id'])
        form = response.forms['resource-edit']

        assert_equals(
            form['validation_options'].value, json.dumps(
                value, indent=2, sort_keys=True))

        value = {
            'delimiter': ';',
            'headers': 2,
            'skip_rows': ['#'],
            'skip_tests': ['blank-rows'],
        }

        json_value = json.dumps(value)

        form['url'] = 'https://example.com/data.csv'
        form['validation_options'] = json_value

        submit_and_follow(app, form, env, 'save')

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['validation_options'], value)

@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
class TestResourceValidationOnCreateForm(object):

    @classmethod
    def _apply_config_changes(cls, cfg):
        cfg['ckanext.validation.run_on_create_sync'] = True

    def setup(self):
        reset_db()
        if not tables_exist():
            create_tables()

    @mock_uploads
    def test_resource_form_create_valid(self, mock_open, app):
        dataset = Dataset()

        app = self._get_test_app()
        env, response = _get_resource_new_page_as_sysadmin(app, dataset['id'])
        form = response.forms['resource-edit']

        upload = ('upload', 'valid.csv', VALID_CSV)

        valid_stream = io.BufferedReader(io.BytesIO(VALID_CSV))

        with mock.patch('io.open', return_value=valid_stream):

            submit_and_follow(app, form, env, 'save', upload_files=[upload])

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['validation_status'], 'success')
        assert 'validation_timestamp' in dataset['resources'][0]

    @mock_uploads
    def test_resource_form_create_invalid(self, mock_open, app):
        dataset = Dataset()

        app = self._get_test_app()
        env, response = _get_resource_new_page_as_sysadmin(app, dataset['id'])
        form = response.forms['resource-edit']

        upload = ('upload', 'invalid.csv', INVALID_CSV)

        invalid_stream = io.BufferedReader(io.BytesIO(INVALID_CSV))

        with mock.patch('io.open', return_value=invalid_stream):

            response = webtest_submit(
                form, 'save', upload_files=[upload], extra_environ=env)

        assert_in('validation', response.body)
        assert_in('missing-value', response.body)
        assert_in('Row 2 has a missing value in column 4', response.body)

@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
class TestResourceValidationOnUpdateForm(object):

    @classmethod
    def _apply_config_changes(cls, cfg):
        cfg['ckanext.validation.run_on_update_sync'] = True

    def setup(self):
        reset_db()
        if not tables_exist():
            create_tables()

    @mock_uploads
    def test_resource_form_update_valid(self, mock_open, app):

        dataset = Dataset(resources=[
            {
                'url': 'https://example.com/data.csv'
            }
        ])

        app = self._get_test_app()
        env, response = _get_resource_update_page_as_sysadmin(
            app, dataset['id'], dataset['resources'][0]['id'])
        form = response.forms['resource-edit']

        upload = ('upload', 'valid.csv', VALID_CSV)

        valid_stream = io.BufferedReader(io.BytesIO(VALID_CSV))

        with mock.patch('io.open', return_value=valid_stream):

            submit_and_follow(app, form, env, 'save', upload_files=[upload])

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['validation_status'], 'success')
        assert 'validation_timestamp' in dataset['resources'][0]

    @mock_uploads
    def test_resource_form_update_invalid(self, mock_open, app):

        dataset = Dataset(resources=[
            {
                'url': 'https://example.com/data.csv'
            }
        ])

        app = self._get_test_app()
        env, response = _get_resource_update_page_as_sysadmin(
            app, dataset['id'], dataset['resources'][0]['id'])
        form = response.forms['resource-edit']

        upload = ('upload', 'invalid.csv', INVALID_CSV)

        invalid_stream = io.BufferedReader(io.BytesIO(INVALID_CSV))

        with mock.patch('io.open', return_value=invalid_stream):

            response = webtest_submit(
                form, 'save', upload_files=[upload], extra_environ=env)

        assert_in('validation', response.body)
        assert_in('missing-value', response.body)
        assert_in('Row 2 has a missing value in column 4', response.body)

@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
class TestResourceValidationFieldsPersisted(object):

    @classmethod
    def _apply_config_changes(cls, cfg):
        cfg['ckanext.validation.run_on_update_sync'] = False
        cfg['ckanext.validation.run_on_update_sync'] = False

    def setup(self):
        reset_db()
        if not tables_exist():
            create_tables()

    def test_resource_form_fields_are_persisted(self, app):

        dataset = Dataset(resources=[
            {
                'url': 'https://example.com/data.csv',
                'validation_status': 'success',
                'validation_timestamp': datetime.datetime.now().isoformat()
            }
        ])

        app = self._get_test_app()
        env, response = _get_resource_update_page_as_sysadmin(
            app, dataset['id'], dataset['resources'][0]['id'])
        form = response.forms['resource-edit']

        form['description'] = 'test desc'

        submit_and_follow(app, form, env, 'save')

        dataset = call_action('package_show', id=dataset['id'])

        assert_equals(dataset['resources'][0]['validation_status'], 'success')
        assert 'validation_timestamp' in dataset['resources'][0]
        assert_equals(dataset['resources'][0]['description'], 'test desc')
