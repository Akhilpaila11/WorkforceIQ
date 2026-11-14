"""Deterministic synthetic data generator (implemented in Phase 3).

Produces CSV, JSON and SQL seed files plus separate ground-truth files and a SHA-256
manifest. Design: docs/06-synthetic-data-and-evaluation.md.

Rules: never read the system clock; one seeded ``random.Random`` per generation stage;
explicit sorting before every export; never import the backend's detection engine.
"""
