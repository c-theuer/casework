from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in app/models/.

    db/schema.sql remains the source of truth for DDL (it's what
    docker-compose and CI actually apply) -- these models are a query/
    persistence layer over that schema, not a migration tool. Keep columns
    here in sync with schema.sql by hand.
    """
