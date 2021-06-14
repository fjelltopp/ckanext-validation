import pytest

from ckanext.validation.model import tables_exist, create_tables


@pytest.fixture(scope='session')
def log():
    def fixture(struct):
        # Pack errors/report to tuples list log:
        # - format for errors: (row-number, column-number, code)
        # - format for report: (table-number, row-number, column-number, code)
        result = []

        def pack_error(error, table_number='skip'):
            error = dict(error)
            error = [
                error.get('row-number'),
                error.get('column-number'),
                error.get('code'),
            ]
            if table_number != 'skip':
                error = [table_number] + error
            return tuple(error)
        if isinstance(struct, list):
            for error in struct:
                result.append(pack_error(error))
        if isinstance(struct, dict):
            for table_number, table in enumerate(struct['tables'], start=1):
                for error in table['errors']:
                    result.append(pack_error(error, table_number))
        return result
    return fixture


@pytest.fixture
def initdb():
    if not tables_exist():
        create_tables()
