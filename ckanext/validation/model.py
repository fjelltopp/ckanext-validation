# encoding: utf-8

import datetime
import uuid
import logging

from sqlalchemy import Column, Unicode, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSON

from ckan.model.meta import metadata
from ckan.model import meta

log = logging.getLogger(__name__)


def make_uuid():
    return str(uuid.uuid4())


Base = declarative_base(metadata=metadata)


class Validation(Base):
    __tablename__ = u'validation'

    id = Column(Unicode, primary_key=True, default=make_uuid)
    resource_id = Column(Unicode)
    status = Column(Unicode, default=u'created')
    created = Column(DateTime, default=datetime.datetime.utcnow)
    finished = Column(DateTime)
    report = Column(JSON)
    error = Column(JSON)


def create_tables():
    engine = meta.engine
    Validation.__table__.create(bind=engine)

    log.info(u'Validation database tables created')


def tables_exist():
    try:
        from sqlalchemy import inspect
        engine = meta.engine
        if engine is None:
            log.warning(
                'Validation tables could not be checked because the database '
                'engine is not available'
            )
            return False
        inspector = inspect(engine)
        return 'validation' in inspector.get_table_names()
    except Exception as e:
        log.warning(f'Error checking if validation tables exist: {e}')
        return False
