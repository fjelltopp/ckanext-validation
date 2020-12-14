import datetime

from nose.tools import assert_equals, assert_in

import pytest

from ckan.tests.helpers import reset_db
from ckan.tests import factories

import ckan.model as model
import ckanext.validation.model as vmodel

from ckantoolkit import config

from ckanext.validation.helpers import (
    get_validation_badge,
    validation_extract_report_from_errors,
)
from ckanext.validation.model import create_tables, tables_exist


@pytest.fixture
def initdb():
    model.Session.remove()
    model.Session.configure(bind=model.meta.engine)
    if not vmodel.tables_exist():
        vmodel.create_tables()


@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
@pytest.mark.ckan_config(u'ckanext.validation.run_on_create_sync', False)
@pytest.mark.ckan_config(u'ckan.plugins', u'validation')
@pytest.mark.usefixtures(u'with_plugins')
@pytest.mark.skip(reason="All TestBadges tests fail in 2.9")
class TestBadges(object):

    @classmethod
    def setup_class(cls):
        cls._original_config = dict(config)
        config['ckanext.validation.run_on_create_sync'] = False

        reset_db()
        if not tables_exist():
            create_tables()

    @classmethod
    def teardown_class(cls):

        config.clear()
        config.update(cls._original_config)

        reset_db()

    def test_get_validation_badge_no_validation(self, app):

        resource = factories.Resource(
            format='CSV',
        )

        assert_equals(get_validation_badge(resource), '')

    def test_get_validation_badge_success(self, app):

        resource = factories.Resource(
            format='CSV',
            validation_status='success',
            validation_timestamp=str(datetime.datetime.utcnow())
        )

        out = get_validation_badge(resource)

        assert 'href="/dataset/{}/resource/{}/validation"'.format(
            resource['package_id'], resource['id']) in out
        assert 'src="/images/badges/data-success-flat.svg"' in out
        assert 'alt="Valid data"' in out
        assert 'title="{}"'.format(resource['validation_timestamp']) in out

    def test_get_validation_badge_failure(self, app):

        resource = factories.Resource(
            format='CSV',
            validation_status='failure',
            validation_timestamp=str(datetime.datetime.utcnow())
        )

        out = get_validation_badge(resource)

        assert 'href="/dataset/{}/resource/{}/validation"'.format(
            resource['package_id'], resource['id']) in out
        assert 'src="/images/badges/data-failure-flat.svg"' in out
        assert 'alt="Invalid data"' in out
        assert 'title="{}"'.format(resource['validation_timestamp']) in out

    def test_get_validation_badge_error(self, app):

        resource = factories.Resource(
            format='CSV',
            validation_status='error',
            validation_timestamp=str(datetime.datetime.utcnow())
        )

        out = get_validation_badge(resource)

        assert 'href="/dataset/{}/resource/{}/validation"'.format(
            resource['package_id'], resource['id']) in out
        assert 'src="/images/badges/data-error-flat.svg"' in out
        assert 'alt="Error during validation"' in out
        assert 'title="{}"'.format(resource['validation_timestamp']) in out

    def test_get_validation_badge_other(self, app):

        resource = factories.Resource(
            format='CSV',
            validation_status='not-sure',
        )

        out = get_validation_badge(resource)

        assert 'href="/dataset/{}/resource/{}/validation"'.format(
            resource['package_id'], resource['id']) in out
        assert 'src="/images/badges/data-unknown-flat.svg"' in out
        assert 'alt="Data validation unknown"' in out
        assert 'title=""' in out


@pytest.mark.usefixtures(u'initdb')
@pytest.mark.usefixtures(u'clean_db')
@pytest.mark.ckan_config(u'ckanext.validation.run_on_create_sync', False)
@pytest.mark.ckan_config(u'ckan.plugins', u'validation')
@pytest.mark.usefixtures(u'with_plugins')
class TestExtractReportFromErrors(object):

    @pytest.mark.skip(reason="Test fails in 2.9")
    def test_report_extracted(self, app):

        report = {
            'tables': [{'source': '/some/path'}],
            'error-count': 8
        }

        errors = {
          'some_field': ['Some error'],
          'validation': [report],
        }

        extracted_report, errors = validation_extract_report_from_errors(
            errors)

        assert_equals(extracted_report, report)
        assert_equals(errors['some_field'], ['Some error'])
        assert str(errors['validation'][0]).strip().startswith(
            'There are validation issues with this file')

        assert_in('data-module="modal-dialog"', str(errors['validation'][0]))

    def test_report_not_extracted(self, app):

        errors = {
          'some_field': ['Some error'],
          'some_other_field': ['Some other error']
        }

        report, errors = validation_extract_report_from_errors(errors)

        assert report is None
        assert_equals(errors['some_field'], ['Some error'])
        assert_equals(errors['some_other_field'], ['Some other error'])
