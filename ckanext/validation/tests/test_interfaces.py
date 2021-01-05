import mock
from nose.tools import assert_equals

import pytest

import ckan.model as model
import ckanext.validation.model as vmodel

from ckan import plugins as p
from ckan.tests import helpers, factories

from ckanext.validation.interfaces import IDataValidation
from ckanext.validation.tests.helpers import VALID_REPORT


@pytest.fixture
def initdb():
    model.Session.remove()
    model.Session.configure(bind=model.meta.engine)
    if not vmodel.tables_exist():
        vmodel.create_tables()

@pytest.fixture
def count_calls():
    calls = 0

    def reset_counter(self):
        self.calls = 0

    def can_validate(self, context, data_dict):
        self.calls += 1

        if data_dict.get('my_custom_field') == 'xx':
            return False

        return True

class TestPlugin(object):

    calls = 0

    def reset_counter(self):
        self.calls = 0

    def can_validate(self, context, data_dict):
        self.calls += 1

        if data_dict.get('my_custom_field') == 'xx':
            return False

        return True


def _get_plugin_calls():
    for plugin in p.PluginImplementations(IDataValidation):
        return plugin.calls


class BaseTestInterfaces(object):

    @classmethod
    def setup_class(cls):

        super(BaseTestInterfaces, cls).setup_class()

        if not p.plugin_loaded('test_validation_plugin'):
            p.load('test_validation_plugin')

    @classmethod
    def teardown_class(cls):

        super(BaseTestInterfaces, cls).teardown_class()

        if p.plugin_loaded('test_validation_plugin'):
            p.unload('test_validation_plugin')

    def setup(self):

        super(BaseTestInterfaces, self).setup()

        for plugin in p.PluginImplementations(IDataValidation):
            return plugin.reset_counter()


@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
@pytest.mark.ckan_config(u'ckan.plugins', u'validation')
@pytest.mark.usefixtures(u'with_plugins')
@pytest.mark.skip(reason="All interface tests fail in 2.9")
class TestInterfaceSync(object):

    @classmethod
    def _apply_config_changes(cls, cfg):
        cfg['ckanext.validation.run_on_create_sync'] = True
        cfg['ckanext.validation.run_on_update_sync'] = True

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @pytest.mark.ckan_config(u'ckanext.validation.run_on_update_async', False)
    @mock.patch('ckanext.validation.jobs.validate',
                return_value=VALID_REPORT)
    def test_can_validate_called_on_create_sync(self, mock_validation, app):

        dataset = factories.Dataset()
        helpers.call_action(
            'resource_create',
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id']
        )
        assert_equals(_get_plugin_calls(), 1)

        assert mock_validation.called

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @pytest.mark.ckan_config(u'ckanext.validation.run_on_update_async', False)
    @mock.patch('ckanext.validation.jobs.validate')
    def test_can_validate_called_on_create_sync_no_validation(self, mock_validation, app):

        dataset = factories.Dataset()
        helpers.call_action(
            'resource_create',
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id'],
            my_custom_field='xx',
        )
        assert_equals(_get_plugin_calls(), 1)

        assert not mock_validation.called

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @pytest.mark.ckan_config(u'ckanext.validation.run_on_update_async', False)
    @mock.patch('ckanext.validation.jobs.validate',
                return_value=VALID_REPORT)
    def test_can_validate_called_on_update_sync(self, mock_validation, app):

        dataset = factories.Dataset()
        resource = factories.Resource(package_id=dataset['id'])
        helpers.call_action(
            'resource_update',
            id=resource['id'],
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id']
        )
        assert_equals(_get_plugin_calls(), 2)  # One for create and one for update

        assert mock_validation.called

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @pytest.mark.ckan_config(u'ckanext.validation.run_on_update_async', False)
    @mock.patch('ckanext.validation.jobs.validate')
    def test_can_validate_called_on_update_sync_no_validation(self, mock_validation, app):

        dataset = factories.Dataset()
        resource = factories.Resource(package_id=dataset['id'])
        helpers.call_action(
            'resource_update',
            id=resource['id'],
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id'],
            my_custom_field='xx',
        )
        assert_equals(_get_plugin_calls(), 2)  # One for create and one for update

        assert not mock_validation.called

@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
@pytest.mark.ckan_config(u'ckan.plugins', u'validation')
@pytest.mark.usefixtures(u'with_plugins')
@pytest.mark.skip(reason="All interface tests fail in 2.9")
class TestInterfaceAsync(object):

    @classmethod
    def _apply_config_changes(cls, cfg):
        cfg['ckanext.validation.run_on_create_sync'] = False
        cfg['ckanext.validation.run_on_update_sync'] = False

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @mock.patch('ckanext.validation.logic.enqueue_job')
    def test_can_validate_called_on_create_async(self, mock_validation, app):

        dataset = factories.Dataset()
        helpers.call_action(
            'resource_create',
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id']
        )
        assert_equals(_get_plugin_calls(), 1)

        assert mock_validation.called

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @mock.patch('ckanext.validation.logic.enqueue_job')
    def test_can_validate_called_on_create_async_no_validation(self, mock_validation, app):

        dataset = factories.Dataset()
        helpers.call_action(
            'resource_create',
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id'],
            my_custom_field='xx',
        )
        assert_equals(_get_plugin_calls(), 1)

        assert not mock_validation.called

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @pytest.mark.ckan_config(u'ckanext.validation.run_on_update_async', True)
    @mock.patch('ckanext.validation.logic.enqueue_job')
    def test_can_validate_called_on_update_async(self, mock_validation, app):

        dataset = factories.Dataset()
        resource = factories.Resource(package_id=dataset['id'])
        helpers.call_action(
            'resource_update',
            id=resource['id'],
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id']
        )
        assert_equals(_get_plugin_calls(), 1)

        assert mock_validation.called

    @pytest.mark.ckan_config(u'ckanext.validation.run_on_create_async', False)
    @pytest.mark.ckan_config(u'ckanext.validation.run_on_update_async', True)
    @mock.patch('ckanext.validation.logic.enqueue_job')
    def test_can_validate_called_on_update_async_no_validation(self, mock_validation, app):

        dataset = factories.Dataset()
        resource = factories.Resource(package_id=dataset['id'])
        helpers.call_action(
            'resource_update',
            id=resource['id'],
            url='https://example.com/data.csv',
            format='CSV',
            package_id=dataset['id'],
            my_custom_field='xx',

        )
        assert_equals(_get_plugin_calls(), 1)

        assert not mock_validation.called
