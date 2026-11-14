"""Phase 5 analysis API on the starter dataset (generated once into a temporary folder and
database), plus empty-database, boundary and failure cases."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.config import Settings
from app.core.database import create_db_engine
from app.main import create_app
from app.modules.analytics import sql_repositories
from datagen.loader import load_dataset
from datagen.pipeline import run as generate_files
from tests.conftest import sqlite_url

pytestmark = pytest.mark.integration
API = "/api/v1"
TYPES = (
    "ALLOCATION_EXCEEDS_AVAILABILITY",
    "EXPIRED_SKILL_TREATED_AS_CURRENT",
    "DUPLICATE_DEMAND",
    "OVERLAPPING_ALLOCATION_CONFLICT",
)


def client_for(engine: Engine, generated: Path | None = None, **kw) -> TestClient:
    settings = Settings(
        _env_file=None,
        env="test",
        log_level="ERROR",
        data_output_dir=generated or Path("does-not-exist"),
    )
    return TestClient(create_app(settings, engine=engine), **kw)


@pytest.fixture(scope="module")
def starter(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Engine, Path, dict]]:
    root = tmp_path_factory.mktemp("analysis")
    dataset, manifest = generate_files("starter", out_root=root / "generated")
    db = root / "starter.sqlite3"
    load_dataset(dataset.tables, sqlite_url(db))
    engine = create_db_engine(sqlite_url(db))
    yield engine, root / "generated", manifest
    engine.dispose()


@pytest.fixture(scope="module")
def api(starter) -> Iterator[TestClient]:
    engine, generated, _ = starter
    with client_for(engine, generated) as client:
        yield client


@pytest.fixture(scope="module")
def run(api) -> dict:
    response = api.post(f"{API}/analysis/runs")
    assert response.status_code == 201, response.text
    return response.json()


def sql(engine: Engine, statement: str, **params: object) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(statement), params)]


def all_items(api: TestClient, path: str, **params: object) -> list[dict]:
    items, page = [], 1
    while True:
        body = api.get(API + path, params={**params, "page": page, "page_size": 200}).json()
        items += body["items"]
        if page >= body["pages"]:
            return items
        page += 1


# ------------------------------------------------------------------ run, persistence, repeatability
def test_run_succeeds_and_records_traceability(run, starter):
    engine, _, manifest = starter
    assert run["status"] == "SUCCEEDED" and run["run_type"] == "FULL_PIPELINE"
    assert run["as_of_date"] == manifest["dataset"]["as_of_date"]
    assert len(run["rules_sha256"]) == 64 and run["rules_version"] == "1.0.0"
    assert run["finished_at"] and run["error_message"] is None
    summary = run["summary"]
    assert summary["window"] == {"start": "2026-03-02", "end": "2026-03-29", "weeks": 4}
    assert summary["assumptions"] and summary["demand"]["duplicate_lines_excluded"] == 5
    audit = sql(
        engine,
        "SELECT action FROM audit_event WHERE entity_id = :r ORDER BY audit_id",
        r=run["run_id"],
    )
    assert [a for (a,) in audit] == ["CREATE", "STATUS_CHANGE"]


def test_results_are_persisted_and_match_the_summary(run, starter):
    engine, _, _ = starter
    rid, s = run["run_id"], run["summary"]

    def count(table: str) -> int:
        return sql(engine, f"SELECT COUNT(*) FROM {table} WHERE run_id = :r", r=rid)[0][0]

    assert count("gap_analysis") == s["gaps"]["rows"] > 0
    assert count("recommendation") == s["recommendations"]["count"] > 0
    assert count("exception_finding") == s["findings"]["count"]
    assert count("forecast_result") == s["forecast"]["rows"] > 0
    assert count("capacity_snapshot") > 0
    # stored identities (BR-CAP-009, BR-GAP-005, resolution identity)
    assert sql(
        engine,
        "SELECT COUNT(*) FROM gap_analysis WHERE run_id = :r AND (ABS(gap_hours - "
        "(demand_hours - committed_hours)) > 0.01 OR ABS(reallocated_hours + trained_hours + "
        "hire_hours + unresolved_hours - gap_hours) > 0.01)",
        r=rid,
    ) == [(0,)]


def _content(api: TestClient, run_id: str) -> tuple:
    gaps = [
        {k: v for k, v in g.items() if k not in ("gap_id", "run_id")}
        for g in all_items(api, "/gap-analysis", run_id=run_id)
    ]
    recs = [
        {
            k: v
            for k, v in r.items()
            if k not in ("recommendation_id", "run_id", "gap_links", "source_refs")
        }
        for r in all_items(api, "/recommendations", run_id=run_id)
    ]
    findings = [
        {k: v for k, v in f.items() if k not in ("finding_id", "run_id")}
        for f in all_items(api, "/exceptions", run_id=run_id)
    ]
    return gaps, recs, findings


def test_rerun_is_deterministic_and_history_is_preserved(api, run):
    second = api.post(f"{API}/analysis/runs").json()
    assert second["run_id"] != run["run_id"]
    assert second["summary"] == run["summary"]
    assert _content(api, second["run_id"]) == _content(api, run["run_id"])
    runs = {r["run_id"] for r in api.get(f"{API}/analysis/runs").json()["items"]}
    assert {run["run_id"], second["run_id"]} <= runs  # earlier results stay queryable


# ------------------------------------------------------------------ detection evaluation
def test_detection_matches_the_separate_ground_truth(api, run, starter):
    _, _, manifest = starter
    evaluation = api.get(f"{API}/exceptions/evaluation", params={"run_id": run["run_id"]}).json()
    result = evaluation["evaluation"]
    assert result["available"] is True and result["ground_truth"].endswith("ground_truth.csv")
    for kind in TYPES:
        scores = result["per_type"][kind]
        assert scores["tp"] == manifest["anomalies"][kind]["ground_truth_rows"], kind
        assert (scores["fp"], scores["fn"]) == (0, 0), kind
        assert scores["precision"] == scores["recall"] == scores["f1"] == 1.0
    assert result["micro"]["f1"] == 1.0


def test_ground_truth_is_not_in_the_database(starter):
    engine, _, _ = starter
    tables = {t for (t,) in sql(engine, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("ground" in t for t in tables)


def test_findings_api_filters_and_explains(api, run):
    found = all_items(api, "/exceptions", run_id=run["run_id"], anomaly_type="DUPLICATE_DEMAND")
    assert len(found) == 5
    for f in found:
        assert f["rule_id"] == "BR-DEM-004" and f["entity_type"] == "demand_plan"
        assert f["related_ids"] and f["entity_id"] in f["message"] and f["status"] == "OPEN"
    over = all_items(api, "/exceptions", anomaly_type="ALLOCATION_EXCEEDS_AVAILABILITY")
    assert all(f["details"]["allocated_hours"] > f["details"]["net_hours"] for f in over)


# ------------------------------------------------------------------ forecasts
def test_forecast_results_and_rollups(api, run):
    rows = all_items(api, "/forecasts/results")
    assert rows and {r["method"] for r in rows} == {"PLAN_RATIO"}
    assert all(r["week_start_date"] >= "2026-03-02" for r in rows)
    naive = all_items(api, "/forecasts/results", method="NAIVE_PLAN")
    assert all(r["forecast_hours"] == r["planned_hours"] for r in naive)
    total = sum(r["forecast_hours"] for r in rows)
    for group_by in ("total", "role", "project", "skill"):
        groups = all_items(api, "/forecasts/summary", group_by=group_by, period="month")
        assert sum(g["forecast_hours"] for g in groups) == pytest.approx(total, abs=0.05)
    weekly = all_items(api, "/forecasts/summary", group_by="total")
    assert all(
        g["forecast_fte"] == pytest.approx(g["forecast_hours"] / 40, abs=1e-3) for g in weekly
    )
    evaluation = api.get(f"{API}/forecasts/evaluation").json()["evaluation"]
    assert evaluation["available"] is True and len(evaluation["weeks"]) == 4
    ratio = evaluation["methods"]["PLAN_RATIO"]["PROJECT_ROLE_WEEK"]
    assert ratio["points"] > 0 and 0 <= ratio["WAPE"] < 1


# ------------------------------------------------------------------ capacity
def test_capacity_summary_identities(api, run):
    s = api.get(f"{API}/capacity/summary", params={"group_by": "week"}).json()
    totals = s["totals"]
    assert totals["weeks"] == 13
    assert totals["net_hours"] == pytest.approx(
        totals["gross_hours"] - totals["leave_hours"] - totals["training_hours"], abs=0.05
    )
    assert totals["available_hours"] - totals["overallocated_hours"] == pytest.approx(
        totals["net_hours"] - totals["allocated_hours"], abs=0.05
    )
    assert totals["utilization"] == pytest.approx(
        totals["allocated_hours"] / totals["net_hours"], abs=1e-4
    )
    assert totals["fte_net"] == pytest.approx(totals["net_hours"] / (40 * 13), abs=0.01)
    assert sum(g["gross_hours"] for g in s["groups"]) == pytest.approx(totals["gross_hours"])
    assert totals["part_time_and_partial_week_reduction_hours"] > 0  # part-timers exist
    by_role = api.get(f"{API}/capacity/summary", params={"group_by": "role"}).json()
    assert sum(g["net_hours"] for g in by_role["groups"]) == pytest.approx(totals["net_hours"])
    role = by_role["groups"][0]["group"]
    one = api.get(f"{API}/capacity/summary", params={"role_id": role}).json()
    assert one["totals"]["net_hours"] == pytest.approx(by_role["groups"][0]["net_hours"])


# ------------------------------------------------------------------ gaps and recommendations
def test_gap_rows_and_summary(api, run):
    rows = all_items(api, "/gap-analysis")
    assert len(rows) == run["summary"]["gaps"]["rows"]
    for g in rows:
        assert g["committed_hours"] <= g["demand_hours"] + 0.01
        assert 0 <= g["coverage_ratio"] <= 1 and g["source_demand_ids"]
    gaps_only = all_items(api, "/gap-analysis", only_gaps="true", severity="CRITICAL")
    assert gaps_only and all(g["gap_hours"] > 0 and g["severity"] == "CRITICAL" for g in gaps_only)
    summary = all_items(api, "/gap-analysis/summary", group_by="role")
    assert sum(g["gap_hours"] for g in summary) == pytest.approx(
        sum(g["gap_hours"] for g in rows), abs=0.05
    )
    assert summary == sorted(summary, key=lambda g: (-g["gap_hours"], g["group"]))
    for g in summary:  # ratios recomputed from sums (BR-GAP-007)
        assert g["coverage_ratio"] == pytest.approx(
            g["committed_hours"] / g["demand_hours"], abs=1e-4
        )


def test_recommendations_are_traceable(api, run, starter):
    engine, _, _ = starter
    recs = all_items(api, "/recommendations", run_id=run["run_id"])
    assert {r["recommendation_type"] for r in recs} >= {"REALLOCATE", "HIRE"}
    gaps = {g["gap_id"]: g for g in all_items(api, "/gap-analysis", run_id=run["run_id"])}
    for r in recs:
        assert r["rule_ids"] and "BR-REC-001" in r["rule_ids"] and r["explanation"]
        assert r["assumptions"] and r["status"] == "PROPOSED"
        assert r["gap_links"] and all(link["gap_id"] in gaps for link in r["gap_links"])
        assert sum(link["covered_hours"] for link in r["gap_links"]) == pytest.approx(
            r["hours"], abs=0.05
        )
        refs = {ref["type"] for ref in r["source_refs"]}
        assert {"skill", "gap_analysis"} <= refs
        if r["recommendation_type"] != "HIRE":
            assert r["employee_id"] and {"employee", "project", "demand_plan"} <= refs
        else:
            assert r["headcount"] >= 1 and r["hire_type"] in ("PERMANENT", "CONTRACT")
    # resolution per gap equals the hours linked from recommendations of that type
    linked = sql(
        engine,
        "SELECT SUM(l.covered_hours) FROM recommendation_gap_link l JOIN recommendation r "
        "ON r.recommendation_id = l.recommendation_id WHERE r.run_id = :r",
        r=run["run_id"],
    )[0][0]
    resolved = sum(
        g["reallocated_hours"] + g["trained_hours"] + g["hire_hours"] for g in gaps.values()
    )
    assert linked == pytest.approx(resolved, abs=0.5)
    one = api.get(f"{API}/recommendations/{recs[0]['recommendation_id']}").json()
    assert one == recs[0]


def test_no_employee_hours_are_offered_twice(run, starter):
    """Reallocated + trained hours per employee-week never exceed the free hours (BR-GAP-004)."""
    engine, _, _ = starter
    over = sql(
        engine,
        """
        WITH weeks AS (
          SELECT r.employee_id, g.week_start_date, SUM(l.covered_hours) AS used
          FROM recommendation r
          JOIN recommendation_gap_link l ON l.recommendation_id = r.recommendation_id
          JOIN gap_analysis g ON g.gap_id = l.gap_id
          WHERE r.run_id = :r AND r.employee_id IS NOT NULL
          GROUP BY r.employee_id, g.week_start_date)
        SELECT COUNT(*) FROM weeks w JOIN capacity_snapshot c
          ON c.run_id = :r AND c.employee_id = w.employee_id
         AND c.week_start_date = w.week_start_date
        WHERE w.used > MAX(c.free_hours, 0) + 0.01
        """,
        r=run["run_id"],
    )
    assert over == [(0,)]


def test_dashboard_metrics(api, run):
    m = api.get(f"{API}/dashboard/metrics").json()
    assert m["run_id"] in {r["run_id"] for r in api.get(f"{API}/analysis/runs").json()["items"]}
    assert len(m["weekly"]) == 4 and m["top_gaps"]
    assert m["forecast_accuracy"]["available"] is True and m["forecast_accuracy"]["metrics"]
    assert m["detection_evaluation"]["micro"]["f1"] == 1.0
    assert set(m["findings"]) >= set(TYPES)
    week = m["weekly"][0]
    assert week["gap_hours"] == pytest.approx(
        week["demand_hours"] - week["committed_hours"], abs=0.05
    )
    assert m["capacity"]["utilization"] == pytest.approx(
        m["capacity"]["allocated_hours"] / m["capacity"]["net_hours"], abs=1e-4
    )


# ------------------------------------------------------------------ boundaries and errors
def test_forecast_basis_and_other_as_of_date(api, run):
    forecast = api.post(f"{API}/analysis/runs", json={"demand_basis": "FORECAST"}).json()
    assert forecast["parameters"]["demand_basis"] == "FORECAST"
    assert forecast["summary"]["gaps"]["demand_hours"] != run["summary"]["gaps"]["demand_hours"]
    earlier = api.post(f"{API}/analysis/runs", json={"as_of_date": "2026-02-02"}).json()
    assert earlier["summary"]["window"]["weeks"] == 8
    evaluation = earlier["summary"]["detection_evaluation"]
    assert evaluation["available"] is False and "as_of_date" in evaluation["reason"]


@pytest.mark.parametrize(
    "body",
    [{"as_of_date": "2027-01-01"}, {"demand_basis": "GUESS"}, {"unknown": 1}, {"as_of_date": "x"}],
)
def test_invalid_run_requests_are_422(api, body):
    response = api.post(f"{API}/analysis/runs", json=body)
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "path",
    [
        "/analysis/runs/RUN-2026-999999",
        "/recommendations/REC-999999-000001",
        "/gap-analysis?run_id=RUN-2026-999999",
    ],
)
def test_unknown_runs_and_records_are_404(api, path):
    assert api.get(API + path).status_code == 404


def test_empty_database(engine):
    with client_for(engine) as client:
        assert client.get(f"{API}/dashboard/metrics").status_code == 404  # no run yet
        missing = client.post(f"{API}/analysis/runs")
        assert missing.status_code == 422 and "as_of_date" in missing.json()["error"]["message"]
        created = client.post(f"{API}/analysis/runs", json={"as_of_date": "2026-03-04"})
        assert created.status_code == 201
        summary = created.json()["summary"]
        assert summary["gaps"]["rows"] == 0 and summary["recommendations"]["count"] == 0
        assert summary["detection_evaluation"]["available"] is False
        assert client.get(f"{API}/gap-analysis").json()["total"] == 0
        assert client.get(f"{API}/capacity/summary").json()["totals"] is None


def test_failed_run_is_recorded_without_partial_results(starter, monkeypatch):
    engine, generated, _ = starter

    def boom(self, run_id, result):
        self._capacity(run_id, result)  # some rows are written before the failure
        raise RuntimeError("disk full")

    monkeypatch.setattr(sql_repositories.SqlAnalysisWriter, "write", boom)
    with client_for(engine, generated, raise_server_exceptions=False) as client:
        response = client.post(f"{API}/analysis/runs")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        failed = client.get(f"{API}/analysis/runs", params={"status": "FAILED"}).json()["items"]
        (run,) = failed
        assert run["error_message"] == "RuntimeError: disk full" and run["finished_at"]
        assert sql(
            engine, "SELECT COUNT(*) FROM capacity_snapshot WHERE run_id = :r", r=run["run_id"]
        ) == [(0,)]
        conflict = client.get(f"{API}/gap-analysis", params={"run_id": run["run_id"]})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "CONFLICT"
