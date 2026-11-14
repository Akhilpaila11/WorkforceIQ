"""The Phase 1 folder structure and required files exist."""

from __future__ import annotations

from pathlib import Path

import pytest

REQUIRED_FILES = [
    "README.md",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".env.example",
    "docs/PROGRESS.md",
    "docs/01-requirements.md",
    "docs/02-assumptions-and-decisions.md",
    "docs/03-business-rules.md",
    "docs/04-architecture.md",
    "docs/05-data-model.md",
    "docs/06-synthetic-data-and-evaluation.md",
    "backend/pyproject.toml",
    "backend/config/business_rules.toml",
    "backend/config/generator.starter.toml",
    "backend/config/generator.full.toml",
    "backend/app/core/config.py",
    "scripts/check-prereqs.ps1",
    # Phase 2
    ".vscode/settings.json",
    "docs/07-data-dictionary.md",
    "backend/alembic.ini",
    "backend/migrations/env.py",
    "backend/migrations/script.py.mako",
    "backend/migrations/versions/0001_initial_schema.py",
    "backend/app/core/database.py",
    "backend/app/db/registry.py",
    "backend/app/db/data_dictionary.py",
    "backend/app/modules/workforce/models.py",
    "backend/app/modules/projects/models.py",
    "backend/app/modules/analytics/models.py",
]

PYTHON_PACKAGES = [
    "backend/app",
    "backend/app/core",
    "backend/app/db",
    "backend/app/domain",
    "backend/app/modules",
    "backend/app/modules/workforce",
    "backend/app/modules/projects",
    "backend/app/modules/analytics",
    "backend/app/modules/reporting",
    "backend/app/api",
    "backend/app/api/v1",
    "backend/datagen",
]

OTHER_DIRS = ["backend/migrations", "backend/tests/integration", "frontend", "data/generated"]


@pytest.mark.parametrize("rel", REQUIRED_FILES)
def test_required_file_exists(repo_root: Path, rel: str) -> None:
    assert (repo_root / rel).is_file(), rel


@pytest.mark.parametrize("rel", PYTHON_PACKAGES)
def test_python_package_has_init(repo_root: Path, rel: str) -> None:
    assert (repo_root / rel / "__init__.py").is_file(), rel


@pytest.mark.parametrize("rel", OTHER_DIRS)
def test_directory_exists(repo_root: Path, rel: str) -> None:
    assert (repo_root / rel).is_dir(), rel


def test_real_env_file_and_databases_are_git_ignored(repo_root: Path) -> None:
    ignored = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored and "!.env.example" in ignored
    assert "data/db/" in ignored and "*.sqlite3" in ignored


def test_repository_root_is_the_project_folder(repo_root: Path) -> None:
    assert repo_root.name == "WorkforceIQ"
    assert (repo_root / ".git").is_dir()


def test_domain_kernel_has_no_framework_imports(repo_root: Path) -> None:
    for py in (repo_root / "backend/app/domain").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "import fastapi" not in text and "from fastapi" not in text, py
        assert "import sqlalchemy" not in text and "from sqlalchemy" not in text, py
