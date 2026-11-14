"""REST API (Phase 4) against isolated SQLite databases.

* ``api`` / ``db``: the Phase 3 starter dataset, generated in memory and loaded into a
  temporary database once per module (about 2 s; the full dataset is never generated here).
* ``empty_api``: a freshly migrated, empty database.

Expected values are read from the database with plain SQL, independently of the API code.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.core.database import create_db_engine
from app.main import create_app
from datagen.config import load_config
from datagen.loader import load_dataset
from datagen.pipeline import generate
from tests.conftest import sqlite_url

pytestmark = pytest.mark.integration
API = "/api/v1"
LISTS = {
    "/employees": "employee",
    "/roles": "role",
    "/skills": "skill",
    "/projects": "project",
    "/allocations": "allocation",
    "/availability": "availability",
    "/training": "training",
}


def make_client(engine: Engine) -> TestClient:
    settings = Settings(_env_file=None, env="test", log_level="WARNING")
    return TestClient(create_app(settings, engine=engine))


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    path: Path = tmp_path_factory.mktemp("api") / "starter.sqlite3"
    dataset = generate(load_config("starter"))
    load_dataset(dataset.tables, sqlite_url(path))
    engine = create_db_engine(sqlite_url(path))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def api(db: Engine) -> Iterator[TestClient]:
    with make_client(db) as client:
        yield client


@pytest.fixture
def empty_api(engine: Engine) -> Iterator[TestClient]:
    with make_client(engine) as client:
        yield client


def sql(engine: Engine, statement: str, **params: object) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(statement), params)]


def get_all(client: TestClient, path: str, **params: object) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        body = client.get(API + path, params={**params, "page": page, "page_size": 200}).json()
        items += body["items"]
        if page >= body["pages"]:
            return items
        page += 1


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code and error["message"] and error["request_id"]
    return error


# ------------------------------------------------------------------ platform
def test_health_reports_database_and_schema(api):
    r = api.get(f"{API}/health", headers={"X-Request-ID": "req-123"})
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "req-123"
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == {"ok": True, "dialect": "sqlite", "schema_revision": "0001"}


def test_swagger_and_openapi_are_exposed(api):
    assert api.get("/docs").status_code == 200
    spec = api.get("/openapi.json").json()
    expected = {
        "/health",
        "/employees",
        "/employees/{employee_id}",
        "/employees/{employee_id}/skills",
        "/roles",
        "/skills",
        "/projects",
        "/projects/{project_id}",
        "/projects/{project_id}/demand",
        "/allocations",
        "/availability",
        "/training",
        "/dashboard/summary",
    }
    assert {API + p for p in expected} <= set(spec["paths"])
    params = {p["name"] for p in spec["paths"][f"{API}/allocations"]["get"]["parameters"]}
    assert {"page", "page_size", "employee_id", "project_id", "status", "date_from"} <= params


def test_cors_allows_the_vite_dev_server_only(api):
    preflight = {"Access-Control-Request-Method": "GET"}
    ok = api.options(f"{API}/employees", headers={"Origin": "http://localhost:5173", **preflight})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = api.get(f"{API}/roles", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_write_methods_are_not_exposed(api):
    assert_error(api.post(f"{API}/employees", json={}), 405, "METHOD_NOT_ALLOWED")
    assert_error(api.get(f"{API}/no-such-endpoint"), 404, "NOT_FOUND")


# ------------------------------------------------------------------ listing and pagination
@pytest.mark.parametrize(("path", "table"), LISTS.items())
def test_list_totals_match_the_database(api, db, path, table):
    body = api.get(API + path).json()
    (count,) = sql(db, f"SELECT COUNT(*) FROM {table}")[0]
    assert count > 0
    assert body["total"] == count
    assert body["page"] == 1 and body["page_size"] == 50
    assert len(body["items"]) == min(50, count)


def test_pagination_walks_every_record_once_in_id_order(api, db):
    pages = [
        api.get(f"{API}/employees", params={"page": n, "page_size": 30}).json()
        for n in (1, 2, 3, 4)
    ]
    assert [p["pages"] for p in pages] == [4] * 4
    assert [len(p["items"]) for p in pages] == [30, 30, 30, 10]
    ids = [e["employee_id"] for p in pages for e in p["items"]]
    assert ids == [r[0] for r in sql(db, "SELECT employee_id FROM employee ORDER BY employee_id")]
    beyond = api.get(f"{API}/employees", params={"page": 5, "page_size": 30}).json()
    assert beyond["items"] == [] and beyond["total"] == 100


def test_get_one_employee_and_project(api, db):
    emp = api.get(f"{API}/employees/EMP-000001").json()
    (role_id,) = sql(db, "SELECT role_id FROM employee WHERE employee_id='EMP-000001'")[0]
    assert emp["employee_id"] == "EMP-000001" and emp["role"]["role_id"] == role_id
    project = api.get(f"{API}/projects/PRJ-2026-000001").json()
    assert project["project_id"] == "PRJ-2026-000001"


# ------------------------------------------------------------------ filters
def test_employee_filters(api, db):
    (role_id,) = sql(db, "SELECT role_id FROM employee GROUP BY role_id ORDER BY COUNT(*) DESC")[0]
    by_role = get_all(api, "/employees", role_id=role_id, status="ACTIVE")
    expected = sql(
        db, "SELECT COUNT(*) FROM employee WHERE role_id=:r AND status='ACTIVE'", r=role_id
    )[0][0]
    assert len(by_role) == expected > 0
    assert all(e["role_id"] == role_id and e["status"] == "ACTIVE" for e in by_role)

    holders = get_all(api, "/employees", skill_id="SKL-000001")
    expected_holders = sql(
        db,
        "SELECT DISTINCT employee_id FROM employee_skill "
        "WHERE skill_id='SKL-000001' AND effective_to IS NULL ORDER BY employee_id",
    )
    assert [e["employee_id"] for e in holders] == [r[0] for r in expected_holders]

    first = api.get(f"{API}/employees/EMP-000001").json()
    found = get_all(api, "/employees", search=first["last_name"].upper())
    assert "EMP-000001" in {e["employee_id"] for e in found}
    assert all(
        first["last_name"].lower() in (e["first_name"] + e["last_name"] + e["email"]).lower()
        for e in found
    )


def test_employee_skills_current_and_history(api, db):
    emp = sql(
        db,
        "SELECT employee_id FROM employee_skill WHERE effective_to IS NOT NULL "
        "ORDER BY employee_id LIMIT 1",
    )[0][0]
    current = get_all(api, f"/employees/{emp}/skills")
    history = get_all(api, f"/employees/{emp}/skills", include_history="true")
    assert all(v["effective_to"] is None and v["employee_id"] == emp for v in current)
    assert len(history) > len(current)
    assert (
        len(history)
        == sql(db, "SELECT COUNT(*) FROM employee_skill WHERE employee_id=:e", e=emp)[0][0]
    )
    strong = get_all(api, f"/employees/{emp}/skills", min_proficiency=4)
    assert all(v["proficiency_level"] >= 4 for v in strong)


def test_catalog_filters(api, db):
    certified = get_all(api, "/skills", requires_certification="true")
    expected = sql(db, "SELECT COUNT(*) FROM skill WHERE requires_certification")[0][0]
    assert len(certified) == expected > 0
    assert all(s["requires_certification"] for s in certified)
    programming = get_all(api, "/skills", category="PROGRAMMING")
    assert programming and all(s["category"] == "PROGRAMMING" for s in programming)
    family = api.get(f"{API}/roles").json()["items"][0]["role_family"]
    assert all(r["role_family"] == family for r in get_all(api, "/roles", role_family=family))


def test_allocation_filters_and_date_window_overlap(api, db):
    window = (date(2026, 2, 2), date(2026, 2, 8))
    rows = sql(
        db,
        "SELECT allocation_id FROM allocation WHERE status='CONFIRMED' "
        "AND start_date <= :to AND end_date >= :frm ORDER BY allocation_id",
        frm=window[0].isoformat(),
        to=window[1].isoformat(),
    )
    found = get_all(api, "/allocations", status="CONFIRMED", date_from=window[0], date_to=window[1])
    assert [a["allocation_id"] for a in found] == [r[0] for r in rows]
    assert rows
    for a in found:
        assert date.fromisoformat(a["start_date"]) <= window[1]
        assert date.fromisoformat(a["end_date"]) >= window[0]

    emp, project = sql(db, "SELECT employee_id, project_id FROM allocation LIMIT 1")[0]
    mine = get_all(api, "/allocations", employee_id=emp, project_id=project)
    assert mine and all(a["employee_id"] == emp and a["project_id"] == project for a in mine)


def test_availability_and_training_filters(api, db):
    leave = get_all(api, "/availability", availability_type="ANNUAL_LEAVE", date_from="2026-01-01")
    expected = sql(
        db,
        "SELECT COUNT(*) FROM availability WHERE availability_type='ANNUAL_LEAVE' "
        "AND (end_date IS NULL OR end_date >= '2026-01-01')",
    )[0][0]
    assert len(leave) == expected > 0
    schedules = get_all(
        api, "/availability", availability_type="WORK_SCHEDULE", date_from="2026-03-01"
    )
    assert any(s["end_date"] is None for s in schedules)  # open-ended schedules overlap any window

    status = sql(db, "SELECT status FROM training GROUP BY status ORDER BY COUNT(*) DESC")[0][0]
    trainings = get_all(api, "/training", status=status)
    assert (
        len(trainings) == sql(db, "SELECT COUNT(*) FROM training WHERE status=:s", s=status)[0][0]
    )
    assert all(t["status"] == status for t in trainings)


def test_project_and_demand_filters(api, db):
    status = sql(db, "SELECT status FROM project GROUP BY status ORDER BY COUNT(*) DESC")[0][0]
    projects = get_all(api, "/projects", status=status)
    assert projects and all(p["status"] == status for p in projects)

    project = "PRJ-2026-000001"
    lines = get_all(api, f"/projects/{project}/demand")
    assert (
        len(lines)
        == sql(db, "SELECT COUNT(*) FROM demand_plan WHERE project_id=:p", p=project)[0][0]
    )
    assert [d["demand_id"] for d in lines] == sorted(d["demand_id"] for d in lines)
    for line in lines:
        kinds = [r["requirement_type"] for r in line["skill_requirements"]]
        assert kinds[0] == "PRIMARY" and kinds.count("PRIMARY") == 1

    jan = get_all(api, f"/projects/{project}/demand", date_from="2026-01-05", date_to="2026-01-25")
    assert jan and all("2026-01-05" <= d["week_start_date"] <= "2026-01-25" for d in jan)
    skill = lines[0]["skill_requirements"][0]["skill_id"]
    needing = get_all(api, f"/projects/{project}/demand", skill_id=skill)
    assert needing and all(
        skill in {r["skill_id"] for r in d["skill_requirements"]} for d in needing
    )
    role = lines[0]["role_id"]
    assert all(
        d["role_id"] == role for d in get_all(api, f"/projects/{project}/demand", role_id=role)
    )


# ------------------------------------------------------------------ invalid input, missing records
@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/employees", {"page": 0}),
        ("/employees", {"page_size": 201}),
        ("/employees", {"page_size": "ten"}),
        ("/employees", {"status": "RETIRED"}),
        ("/employees", {"role_id": "ROLE-1"}),
        ("/employees", {"unknown": "x"}),
        ("/allocations", {"date_from": "2026-02-30"}),
        ("/allocations", {"date_from": "2026-03-01", "date_to": "2026-02-01"}),
        ("/skills", {"requires_certification": "maybe"}),
        ("/employees/EMP-000001/skills", {"min_proficiency": 6}),
    ],
)
def test_invalid_query_parameters_are_422(api, path, params):
    error = assert_error(api.get(API + path, params=params), 422, "VALIDATION_ERROR")
    assert error["details"] and error["details"][0]["loc"][0] == "query"


@pytest.mark.parametrize(
    "path",
    ["/employees/emp-1", "/employees/EMP-1/skills", "/projects/PRJ-26-1", "/projects/X/demand"],
)
def test_malformed_ids_are_422(api, path):
    error = assert_error(api.get(API + path), 422, "VALIDATION_ERROR")
    assert error["details"][0]["loc"][0] == "path"


@pytest.mark.parametrize(
    ("path", "entity"),
    [
        ("/employees/EMP-999999", "employee"),
        ("/employees/EMP-999999/skills", "employee"),
        ("/projects/PRJ-2026-999999", "project"),
        ("/projects/PRJ-2026-999999/demand", "project"),
    ],
)
def test_missing_records_are_404(api, path, entity):
    error = assert_error(api.get(API + path), 404, "NOT_FOUND")
    assert error["details"]["entity"] == entity


def test_unknown_filter_value_returns_empty_page_not_404(api):
    body = api.get(f"{API}/allocations", params={"employee_id": "EMP-999999"}).json()
    assert body == {"items": [], "page": 1, "page_size": 50, "total": 0, "pages": 0}


# ------------------------------------------------------------------ foreign-key integrity
def test_foreign_keys_hold_and_references_resolve_through_the_api(api, db):
    assert sql(db, "PRAGMA foreign_key_check") == []
    allocations = api.get(f"{API}/allocations", params={"page_size": 25}).json()["items"]
    for a in allocations:
        assert api.get(f"{API}/employees/{a['employee_id']}").status_code == 200
        assert api.get(f"{API}/projects/{a['project_id']}").status_code == 200
    roles = {r["role_id"] for r in get_all(api, "/roles")}
    skills = {s["skill_id"] for s in get_all(api, "/skills")}
    assert {a["role_id"] for a in allocations} <= roles
    assert {e["role_id"] for e in get_all(api, "/employees")} <= roles
    lines = get_all(api, "/projects/PRJ-2026-000001/demand")
    assert {r["skill_id"] for d in lines for r in d["skill_requirements"]} <= skills
    assert {t["skill_id"] for t in get_all(api, "/training")} <= skills


# ------------------------------------------------------------------ dashboard summary
def test_summary_totals_come_from_the_database(api, db):
    s = api.get(f"{API}/dashboard/summary").json()
    count = lambda table: sql(db, f"SELECT COUNT(*) FROM {table}")[0][0]  # noqa: E731
    assert s["dataset"]["mode"] == "starter" and s["dataset"]["seed"] == "20261022"
    assert s["employees"]["total"] == count("employee") == sum(s["employees"]["by_status"].values())
    assert s["roles"] == count("role")
    assert s["skills"]["total"] == count("skill")
    assert (
        s["skills"]["current_employee_skills"]
        == sql(db, "SELECT COUNT(*) FROM employee_skill WHERE effective_to IS NULL")[0][0]
    )
    assert s["projects"]["total"] == count("project")
    assert s["demand"]["total"] == count("demand_plan")
    assert s["demand"]["required_hours"] == pytest.approx(
        sql(db, "SELECT SUM(required_hours) FROM demand_plan")[0][0]
    )
    assert s["demand"]["first_week"] == "2025-12-29"
    assert (
        s["allocations"]["total"]
        == count("allocation")
        == sum(s["allocations"]["by_type"].values())
    )
    assert s["availability"]["total"] == count("availability")
    assert s["training"]["by_status"] == dict(
        sql(db, "SELECT status, COUNT(*) FROM training GROUP BY status")
    )


# ------------------------------------------------------------------ empty and unavailable databases
@pytest.mark.parametrize("path", LISTS)
def test_empty_database_returns_empty_pages(empty_api, path):
    r = empty_api.get(API + path)
    assert r.status_code == 200
    assert r.json() == {"items": [], "page": 1, "page_size": 50, "total": 0, "pages": 0}


def test_empty_database_summary_and_lookups(empty_api):
    s = empty_api.get(f"{API}/dashboard/summary").json()
    assert s["dataset"] == {} and s["employees"] == {"total": 0, "by_status": {}}
    assert s["demand"]["required_hours"] == 0 and s["demand"]["first_week"] is None
    assert_error(empty_api.get(f"{API}/employees/EMP-000001"), 404, "NOT_FOUND")
    assert_error(empty_api.get(f"{API}/projects/PRJ-2026-000001/demand"), 404, "NOT_FOUND")
    assert empty_api.get(f"{API}/health").json()["status"] == "ok"


def test_unmigrated_database_is_503(tmp_path):
    engine = create_db_engine(sqlite_url(tmp_path / "blank.sqlite3"))
    try:
        with make_client(engine) as client:
            assert_error(client.get(f"{API}/employees"), 503, "DATABASE_UNAVAILABLE")
            health = client.get(f"{API}/health").json()
            assert health["database"]["schema_revision"] is None
    finally:
        engine.dispose()
