"""Application settings, loaded from environment variables.

Beginner note
-------------
Nothing secret is written in source code. Every value comes from an environment variable
with the ``WFIQ_`` prefix, or from a ``.env`` file in the repository root (git-ignored).
``.env.example`` lists every variable with a safe placeholder.

Usage::

    from app.core.config import get_settings
    settings = get_settings()
    url = settings.database_url()
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

BACKEND_DIR: Path = Path(__file__).resolve().parents[2]
REPO_ROOT: Path = BACKEND_DIR.parent


class MissingSettingError(RuntimeError):
    """Raised when a setting needed for an operation has not been configured."""


class Settings(BaseSettings):
    """Typed, validated configuration for the backend and the data generator."""

    model_config = SettingsConfigDict(
        env_prefix="WFIQ_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also contains VITE_* frontend variables
    )

    # --- application -----------------------------------------------------------
    env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173"

    # --- database --------------------------------------------------------------
    # sqlite (default, decision A-35) or postgresql. The schema works on both.
    db_backend: Literal["sqlite", "postgresql"] = "sqlite"
    sqlite_path: Path = Path("../data/db/workforceiq.sqlite3")
    sqlite_test_path: Path = Path("../data/db/workforceiq_test.sqlite3")
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "workforceiq"
    db_user: str = "workforceiq_app"
    db_password: SecretStr | None = None
    db_echo: bool = False
    test_db_name: str = "workforceiq_test"

    # --- business rules & synthetic data -----------------------------------------
    rules_file: Path = Path("config/business_rules.toml")
    generator_mode: Literal["starter", "full"] = "starter"
    data_output_dir: Path = Path("../data/generated")

    @property
    def cors_origin_list(self) -> list[str]:
        """Comma-separated ``cors_origins`` as a clean list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def database_url(self, *, test: bool = False) -> URL:
        """SQLAlchemy URL for the main (or test) database.

        SQLite: a file under ``data/db`` (no credentials).
        PostgreSQL: ``URL.create`` escapes special characters in the password safely, and
        ``str(url)`` masks the password, so the URL can be logged without leaking it.
        """
        if self.db_backend == "sqlite":
            path = self.resolve_path(self.sqlite_test_path if test else self.sqlite_path)
            return URL.create(drivername="sqlite+pysqlite", database=str(path))
        if self.db_password is None or not self.db_password.get_secret_value():
            raise MissingSettingError(
                "WFIQ_DB_PASSWORD is not set. Copy .env.example to .env and set it."
            )
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.test_db_name if test else self.db_name,
        )

    def resolve_path(self, path: Path) -> Path:
        """Resolve a configured path relative to the ``backend/`` directory."""
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def rules_path(self) -> Path:
        return self.resolve_path(self.rules_file)

    @property
    def generator_config_path(self) -> Path:
        return BACKEND_DIR / "config" / f"generator.{self.generator_mode}.toml"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (cached; FastAPI uses this as a dependency)."""
    return Settings()
