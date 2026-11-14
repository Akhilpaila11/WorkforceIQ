"""Cross-cutting infrastructure: settings, database session, logging, error handling.

Phase 1: ``config`` (settings from environment variables).
Phase 4: ``database`` (engine, session, unit of work), ``logging`` (JSON formatter),
``errors`` (domain exceptions and centralized HTTP mapping).
"""
