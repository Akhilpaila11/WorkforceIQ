"""Persistence infrastructure shared by all modules.

``base``        declarative base, naming convention, timestamp mixin
``types``       portable column types (Decimal hours, UTC timestamps, JSON/JSONB)
``constraints`` reusable CHECK-constraint builders
``models``      platform tables: audit_event, id_sequence, dataset_metadata
``guards``      ORM guard that makes identifiers and declared fields immutable
``repository``  generic repository Protocols + SQLAlchemy implementation
``audit``       audit recorder (append-only change history)
``ids``         database-backed ID allocator
``registry``    imports every model so ``metadata`` is complete (used by Alembic)
``data_dictionary`` generates docs/07-data-dictionary.md from the models
"""
