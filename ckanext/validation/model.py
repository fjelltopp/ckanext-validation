# encoding: utf-8

import datetime
import uuid
import logging

from sqlalchemy import Column, Unicode, DateTime, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSON

from ckan.model.meta import metadata

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
    if metadata.bind is None:
        from ckan.model import meta
        engine = meta.engine
    else:
        engine = metadata.bind

    Validation.__table__.create(engine, checkfirst=True)
    log.info(u'Validation database tables created')


def tables_exist():
    if metadata.bind is None:
        from ckan.model import meta
        engine = meta.engine
    else:
        engine = metadata.bind

    # Return False if engine is not available yet (e.g., during early startup)
    if engine is None:
        return False

    inspector = inspect(engine)
    return inspector.has_table(Validation.__tablename__)
