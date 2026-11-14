"""Settings are read from the environment, validated, and never leak the password."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_DIR, MissingSettingError, Settings


def make_settings() -> Settings:
    # _env_file=None: ignore any real .env so the test is hermetic.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults_without_environment(clean_env: pytest.MonkeyPatch) -> None:
    s = make_settings()
    assert s.api_prefix == "/api/v1"
    assert s.db_port == 5432
    assert s.db_password is None
    assert s.cors_origin_list == ["http://localhost:5173"]
    assert s.rules_path == (BACKEND_DIR / "config" / "business_rules.toml").resolve()
    assert s.generator_config_path.name == "generator.starter.toml"


def test_environment_overrides(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("WFIQ_DB_HOST", "db.internal")
    clean_env.setenv("WFIQ_DB_PORT", "6543")
    clean_env.setenv("WFIQ_GENERATOR_MODE", "full")
    clean_env.setenv("WFIQ_CORS_ORIGINS", "http://a:1, http://b:2 ,")
    s = make_settings()
    assert s.db_host == "db.internal"
    assert s.db_port == 6543
    assert s.generator_config_path.name == "generator.full.toml"
    assert s.cors_origin_list == ["http://a:1", "http://b:2"]


def test_invalid_values_are_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("WFIQ_DB_PORT", "70000")
    with pytest.raises(ValidationError):
        make_settings()
    clean_env.setenv("WFIQ_DB_PORT", "5432")
    clean_env.setenv("WFIQ_GENERATOR_MODE", "huge")
    with pytest.raises(ValidationError):
        make_settings()


def test_sqlite_is_the_default_backend(clean_env: pytest.MonkeyPatch) -> None:
    s = make_settings()
    assert s.db_backend == "sqlite"
    url = s.database_url()
    assert url.drivername == "sqlite+pysqlite"
    assert url.database is not None
    assert url.database.endswith("workforceiq.sqlite3")
    assert s.database_url(test=True).database != url.database
    assert url.password is None


def test_postgresql_url_requires_password(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("WFIQ_DB_BACKEND", "postgresql")
    with pytest.raises(MissingSettingError):
        make_settings().database_url()


def test_database_url_masks_password(clean_env: pytest.MonkeyPatch) -> None:
    secret = "p@ss:w/rd"  # special characters must be escaped, not break the URL
    clean_env.setenv("WFIQ_DB_BACKEND", "postgresql")
    clean_env.setenv("WFIQ_DB_PASSWORD", secret)
    s = make_settings()
    url = s.database_url()
    assert url.password == secret
    assert url.drivername == "postgresql+psycopg"
    assert url.database == "workforceiq"
    assert s.database_url(test=True).database == "workforceiq_test"
    assert secret not in str(url)
    assert secret not in repr(s)
