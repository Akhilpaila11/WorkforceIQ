"""Feature modules of the modular monolith.

Each module follows the same layout (added from Phase 2 onwards)::

    models.py            SQLAlchemy ORM classes - structure only, no business logic
    schemas.py           Pydantic v2 request/response DTOs
    repositories.py      Protocols (interfaces) that services depend on
    sql_repositories.py  SQLAlchemy implementations of those Protocols
    services.py          use-cases; receive repositories through their constructor
    router.py            thin FastAPI routes

Modules talk to each other only through services or repository Protocols.
"""
