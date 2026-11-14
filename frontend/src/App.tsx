import { ReactNode, useState } from "react";
import {
  api,
  apiAll,
  CapacitySummary,
  DataSummary,
  Finding,
  ForecastGroup,
  GapGroup,
  Metrics,
  Named,
  Page,
  Recommendation,
  Run,
  useApi,
} from "./api";

const TABS = ["Overview", "Forecasting", "Skill gaps", "Utilization", "Anomalies", "Recommendations"] as const;
type Tab = (typeof TABS)[number];
const ANOMALIES: Record<string, string> = {
  ALLOCATION_EXCEEDS_AVAILABILITY: "Allocation exceeds availability",
  EXPIRED_SKILL_TREATED_AS_CURRENT: "Expired skill treated as current",
  DUPLICATE_DEMAND: "Duplicate project demand",
  OVERLAPPING_ALLOCATION_CONFLICT: "Overlapping assignment conflict",
  STALE_SKILL: "Stale skill (informational)",
};

const num = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

function State({ loading, error, empty, children }: { loading: boolean; error: string | null; empty?: boolean; children: ReactNode }) {
  if (loading) return <p className="muted">Loading…</p>;
  if (error) return <p className="error">Could not load data: {error}</p>;
  if (empty) return <p className="muted">No data for this selection.</p>;
  return <>{children}</>;
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}

function Pager<T>({ page, onPage }: { page: Page<T>; onPage: (p: number) => void }) {
  if (page.pages <= 1) return <p className="muted">{page.total} rows</p>;
  return (
    <div className="pager">
      <button disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>‹ Prev</button>
      <span>Page {page.page} of {page.pages} · {page.total} rows</span>
      <button disabled={page.page >= page.pages} onClick={() => onPage(page.page + 1)}>Next ›</button>
    </div>
  );
}

function Badge({ value }: { value: string }) {
  return <span className={`badge b-${value.toLowerCase()}`}>{value.replace(/_/g, " ")}</span>;
}

// ------------------------------------------------------------------ reference names
function useNames() {
  return useApi(async () => {
    const [roles, skills, projects] = await Promise.all([
      apiAll<Named>("/roles"),
      apiAll<Named>("/skills"),
      apiAll<Named>("/projects"),
    ]);
    const map = (rows: Named[], key: keyof Named) => Object.fromEntries(rows.map((r) => [r[key] as string, r.name]));
    return { roles: map(roles, "role_id"), skills: map(skills, "skill_id"), projects: map(projects, "project_id") };
  }, []);
}
type Names = { roles: Record<string, string>; skills: Record<string, string>; projects: Record<string, string> };

// ------------------------------------------------------------------ overview
function Overview({ m, names }: { m: Metrics; names: Names }) {
  const summary = useApi(() => api<DataSummary>("/dashboard/summary"), []);
  const findings = Object.entries(m.findings).filter(([k]) => k !== "STALE_SKILL");
  const exceptionCount = findings.reduce((sum, [, bySeverity]) => sum + Object.values(bySeverity).reduce((a, b) => a + b, 0), 0);
  const fa = m.forecast_accuracy;
  return (
    <>
      <div className="grid">
        <Kpi label="Employees" value={summary.data ? num(summary.data.employees.total) : "…"} hint={`${num(m.capacity.active_employees)} active in window`} />
        <Kpi label="Projects" value={summary.data ? num(summary.data.projects.total) : "…"} />
        <Kpi label="Demand (window)" value={`${num(m.demand.window_planned_hours)} h`} hint={`Forecast ${num(m.demand.window_forecast_hours)} h (${m.demand.forecast_method})`} />
        <Kpi label="Net capacity (window)" value={`${num(m.capacity.net_hours)} h`} hint={`${num(m.capacity.fte.net, 1)} FTE`} />
        <Kpi label="Utilization" value={pct(m.capacity.utilization)} hint={`${num(m.capacity.bench_employees)} on bench`} />
        <Kpi label="Skill gap" value={`${num(m.coverage.gap_hours)} h`} hint={`Coverage ${pct(m.coverage.coverage_ratio)}`} />
        <Kpi label="Exceptions" value={num(exceptionCount)} hint="4 anomaly types" />
        <Kpi label="Recommendations" value={num(m.recommendations.count)} hint={`Hire ${num(m.recommendations.hire_headcount)} people`} />
      </div>
      <div className="two">
        <section className="card">
          <h3>Top skill gaps (role · skill)</h3>
          <GapTable rows={m.top_gaps} names={names} />
        </section>
        <section className="card">
          <h3>Model quality</h3>
          <p>
            <b>Forecast ({fa.method})</b>:{" "}
            {fa.available && fa.metrics
              ? `WAPE ${pct(fa.metrics.PROJECT_ROLE_WEEK.WAPE)}, MAE ${num(fa.metrics.PROJECT_ROLE_WEEK.MAE, 1)} h, bias ${pct(fa.metrics.PROJECT_ROLE_WEEK.BIAS)} (${fa.metrics.PROJECT_ROLE_WEEK.points} project-role-weeks)`
              : `not available — ${fa.reason}`}
          </p>
          <b>Anomaly detection vs ground truth</b>
          {m.detection_evaluation.available && m.detection_evaluation.per_type ? (
            <table>
              <thead><tr><th>Type</th><th>TP</th><th>FP</th><th>FN</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
              <tbody>
                {Object.entries(m.detection_evaluation.per_type).map(([k, v]) => (
                  <tr key={k}><td>{ANOMALIES[k]}</td><td>{v.tp}</td><td>{v.fp}</td><td>{v.fn}</td><td>{pct(v.precision)}</td><td>{pct(v.recall)}</td><td>{pct(v.f1)}</td></tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">Not available — {m.detection_evaluation.reason}</p>
          )}
        </section>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ forecasting
function Chart({ rows }: { rows: ForecastGroup[] }) {
  const w = 760, h = 260, pad = 40;
  const max = Math.max(1, ...rows.flatMap((r) => [r.planned_hours, r.forecast_hours]));
  const step = (w - pad * 2) / Math.max(1, rows.length);
  const y = (v: number) => h - pad - (v / max) * (h - pad * 2);
  const line = rows.map((r, i) => `${pad + step * i + step / 2},${y(r.forecast_hours)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="chart" role="img" aria-label="Planned and forecast demand per period">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={pad} x2={w - pad} y1={y(max * f)} y2={y(max * f)} className="grid-line" />
          <text x={4} y={y(max * f) + 4} className="axis">{num(max * f)}</text>
        </g>
      ))}
      {rows.map((r, i) => (
        <g key={r.period}>
          <rect x={pad + step * i + step * 0.2} width={step * 0.6} y={y(r.planned_hours)} height={h - pad - y(r.planned_hours)} className="bar">
            <title>{`${r.period}: planned ${num(r.planned_hours)} h, forecast ${num(r.forecast_hours)} h`}</title>
          </rect>
          <text x={pad + step * i + step / 2} y={h - pad + 16} className="axis" textAnchor="middle">{r.period}</text>
        </g>
      ))}
      <polyline points={line} className="fline" />
      {rows.map((r, i) => <circle key={r.period} cx={pad + step * i + step / 2} cy={y(r.forecast_hours)} r={3.5} className="fdot" />)}
    </svg>
  );
}

function Forecasting({ m, names }: { m: Metrics; names: Names }) {
  const [project, setProject] = useState("");
  const [role, setRole] = useState("");
  const [period, setPeriod] = useState("week");
  const data = useApi(
    () => api<Page<ForecastGroup>>("/forecasts/summary", { run_id: m.run_id, group_by: "total", period, project_id: project, role_id: role, page_size: 200 }),
    [m.run_id, project, role, period],
  );
  const rows = data.data?.items ?? [];
  return (
    <section className="card">
      <div className="filters">
        <label>Project <select value={project} onChange={(e) => setProject(e.target.value)}><option value="">All projects</option>{Object.entries(names.projects).map(([id, n]) => <option key={id} value={id}>{id} · {n}</option>)}</select></label>
        <label>Role <select value={role} onChange={(e) => setRole(e.target.value)}><option value="">All roles</option>{Object.entries(names.roles).map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></label>
        <label>Period <select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="week">Week</option><option value="month">Month</option></select></label>
      </div>
      <p className="legend"><span className="sw bar" /> Planned (de-duplicated) <span className="sw fline" /> Forecast ({m.demand.forecast_method}) — window from {m.window.start}</p>
      <State loading={data.loading} error={data.error} empty={!rows.length}>
        <Chart rows={rows} />
        <table>
          <thead><tr><th>Period</th><th>Planned h</th><th>Forecast h</th><th>Forecast FTE</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.period}><td>{r.period}</td><td>{num(r.planned_hours)}</td><td>{num(r.forecast_hours)}</td><td>{num(r.forecast_fte, 1)}</td></tr>)}</tbody>
        </table>
      </State>
    </section>
  );
}

// ------------------------------------------------------------------ skill gaps
function GapTable({ rows, names }: { rows: GapGroup[]; names: Names }) {
  if (!rows.length) return <p className="muted">No gaps.</p>;
  return (
    <table>
      <thead><tr><th>Role</th><th>Skill</th><th>Demand h</th><th>Coverage</th><th>Gap h</th><th>Gap FTE</th><th>Severity</th></tr></thead>
      <tbody>
        {rows.map((g) => {
          const [role, skill] = g.group.split("|");
          return (
            <tr key={g.group}>
              <td>{names.roles[role] ?? role}</td><td>{names.skills[skill] ?? skill}</td><td>{num(g.demand_hours)}</td>
              <td><div className="meter"><i style={{ width: pct(g.coverage_ratio ?? 0) }} /></div>{pct(g.coverage_ratio)}</td>
              <td>{num(g.gap_hours)}</td><td>{num(g.gap_fte, 1)}</td><td><Badge value={g.worst_severity} /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Gaps({ m, names }: { m: Metrics; names: Names }) {
  const [page, setPage] = useState(1);
  const data = useApi(
    () => api<Page<GapGroup>>("/gap-analysis/summary", { run_id: m.run_id, group_by: "role_skill", only_gaps: true, page, page_size: 25 }),
    [m.run_id, page],
  );
  return (
    <section className="card">
      <p className="muted">
        Demand {num(m.coverage.demand_hours)} h · committed {num(m.coverage.committed_hours)} h · at risk (ineligible staff) {num(m.coverage.at_risk_hours)} h · gap {num(m.coverage.gap_hours)} h · unresolved after recommendations {num(m.coverage.unresolved_hours)} h
      </p>
      <State loading={data.loading} error={data.error} empty={!data.data?.items.length}>
        {data.data && <><GapTable rows={data.data.items} names={names} /><Pager page={data.data} onPage={setPage} /></>}
      </State>
    </section>
  );
}

// ------------------------------------------------------------------ utilization
function Utilization({ m, names }: { m: Metrics; names: Names }) {
  const weeks = useApi(() => api<CapacitySummary>("/capacity/summary", { run_id: m.run_id, group_by: "week" }), [m.run_id]);
  const roles = useApi(() => api<CapacitySummary>("/capacity/summary", { run_id: m.run_id, group_by: "role", date_from: m.window.start }), [m.run_id]);
  const t = weeks.data?.totals;
  const risk = (u: number | null) => (u == null ? "UNAVAILABLE" : u > 1 ? "OVERALLOCATED" : u >= 0.85 ? "HIGH" : u >= 0.5 ? "HEALTHY" : "UNDER_UTILIZED");
  return (
    <State loading={weeks.loading || roles.loading} error={weeks.error ?? roles.error} empty={!t}>
      {t && (
        <>
          <div className="grid">
            <Kpi label="Gross hours" value={num(t.gross_hours)} hint={`Part-time & partial weeks −${num(t.part_time_and_partial_week_reduction_hours)} h`} />
            <Kpi label="Leave / training" value={`${num(t.leave_hours)} / ${num(t.training_hours)}`} />
            <Kpi label="Net capacity" value={`${num(t.net_hours)} h`} hint={`${num(t.fte_net, 1)} FTE`} />
            <Kpi label="Allocated" value={`${num(t.allocated_hours)} h`} hint={`Over-allocated ${num(t.overallocated_hours)} h`} />
            <Kpi label="Available" value={`${num(t.available_hours)} h`} hint={`${num(t.fte_available, 1)} FTE`} />
            <Kpi label="Utilization (all weeks)" value={pct(t.utilization)} hint={`Window: ${pct(m.capacity.utilization)}`} />
          </div>
          <div className="two">
            <section className="card">
              <h3>Risk bands (employee-weeks, window)</h3>
              <div className="bands">{Object.entries(m.risk_bands).map(([k, v]) => <div key={k}><Badge value={k} /><strong>{num(v)}</strong></div>)}</div>
              <h3>By role (window)</h3>
              <table>
                <thead><tr><th>Role</th><th>Net h</th><th>Allocated h</th><th>Utilization</th></tr></thead>
                <tbody>{roles.data?.groups.map((g) => <tr key={g.group}><td>{names.roles[g.group] ?? g.group}</td><td>{num(g.net_hours)}</td><td>{num(g.allocated_hours)}</td><td><Badge value={risk(g.utilization)} /> {pct(g.utilization)}</td></tr>)}</tbody>
              </table>
            </section>
            <section className="card">
              <h3>Weekly capacity</h3>
              <table>
                <thead><tr><th>Week</th><th>Headcount</th><th>Net h</th><th>Allocated h</th><th>Utilization</th></tr></thead>
                <tbody>{weeks.data?.groups.map((g) => (
                  <tr key={g.group} className={g.group >= m.window.start ? "" : "past"}>
                    <td>{g.group}</td><td>{num(g.avg_headcount)}</td><td>{num(g.net_hours)}</td><td>{num(g.allocated_hours)}</td>
                    <td><div className="meter"><i style={{ width: pct(Math.min(1, g.utilization ?? 0)) }} /></div>{pct(g.utilization)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </State>
  );
}

// ------------------------------------------------------------------ anomalies
function Anomalies({ m }: { m: Metrics }) {
  const [type, setType] = useState("ALLOCATION_EXCEEDS_AVAILABILITY");
  const [page, setPage] = useState(1);
  const data = useApi(() => api<Page<Finding>>("/exceptions", { run_id: m.run_id, anomaly_type: type, page, page_size: 20 }), [m.run_id, type, page]);
  return (
    <>
      <div className="grid">
        {Object.entries(ANOMALIES).map(([k, label]) => {
          const bySeverity = m.findings[k] ?? {};
          const total = Object.values(bySeverity).reduce((a, b) => a + b, 0);
          return (
            <button key={k} className={`kpi pick ${type === k ? "on" : ""}`} onClick={() => { setType(k); setPage(1); }}>
              <span>{label}</span><strong>{num(total)}</strong>
              <small>{Object.entries(bySeverity).map(([s, n]) => `${s} ${n}`).join(" · ") || "none"}</small>
            </button>
          );
        })}
      </div>
      <section className="card">
        <State loading={data.loading} error={data.error} empty={!data.data?.items.length}>
          {data.data && (
            <>
              <table>
                <thead><tr><th>Severity</th><th>Rule</th><th>Record</th><th>Week</th><th>Related records</th><th>Explanation</th></tr></thead>
                <tbody>{data.data.items.map((f) => (
                  <tr key={f.finding_id}><td><Badge value={f.severity} /></td><td>{f.rule_id}</td><td>{f.entity_type}<br /><code>{f.entity_id}</code></td><td>{f.week_start_date ?? "—"}</td><td className="ids">{f.related_ids.join(", ") || "—"}</td><td>{f.message}</td></tr>
                ))}</tbody>
              </table>
              <Pager page={data.data} onPage={setPage} />
            </>
          )}
        </State>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ recommendations
function Recommendations({ m, names }: { m: Metrics; names: Names }) {
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const data = useApi(() => api<Page<Recommendation>>("/recommendations", { run_id: m.run_id, recommendation_type: type, page, page_size: 20 }), [m.run_id, type, page]);
  return (
    <>
      <div className="grid">
        {(["", "REALLOCATE", "TRAIN", "HIRE"] as const).map((k) => (
          <button key={k || "ALL"} className={`kpi pick ${type === k ? "on" : ""}`} onClick={() => { setType(k); setPage(1); }}>
            <span>{k || "All actions"}</span>
            <strong>{num(k ? m.recommendations.by_type[k] ?? 0 : m.recommendations.count)}</strong>
            <small>{num(k ? m.recommendations.hours_by_type[k] ?? 0 : Object.values(m.recommendations.hours_by_type).reduce((a, b) => a + b, 0))} h{k === "HIRE" ? ` · ${m.recommendations.hire_headcount} people` : ""}</small>
          </button>
        ))}
      </div>
      <section className="card">
        <State loading={data.loading} error={data.error} empty={!data.data?.items.length}>
          {data.data && (
            <>
              <div className="recs">{data.data.items.map((r) => (
                <article key={r.recommendation_id} className="rec">
                  <header>
                    <Badge value={r.recommendation_type} />
                    <b>{names.roles[r.role_id] ?? r.role_id} · {names.skills[r.skill_id] ?? r.skill_id}</b>
                    <span className="muted">{r.employee_id ?? `${r.headcount} × ${r.hire_type}`}{r.project_id ? ` → ${names.projects[r.project_id] ?? r.project_id}` : ""} · {num(r.hours, 1)} h · {r.period_start} → {r.period_end}</span>
                  </header>
                  <p>{r.explanation}</p>
                  <small className="muted">{r.recommendation_id} · rules {r.rule_ids.join(", ")}</small>
                </article>
              ))}</div>
              <Pager page={data.data} onPage={setPage} />
            </>
          )}
        </State>
      </section>
    </>
  );
}

// ------------------------------------------------------------------ shell
export default function App() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [refresh, setRefresh] = useState(0);
  const [starting, setStarting] = useState<string | null>(null);
  const runs = useApi(() => api<Page<Run>>("/analysis/runs", { status: "SUCCEEDED", page_size: 1 }), [refresh]);
  const hasRun = (runs.data?.total ?? 0) > 0;
  const metrics = useApi(() => (hasRun ? api<Metrics>("/dashboard/metrics") : Promise.resolve(null)), [hasRun, refresh]);
  const names = useNames();

  async function startRun() {
    setStarting("Running analysis… (starter data takes about a second; the full dataset about a minute)");
    try {
      await api<Run>("/analysis/runs", {}, { method: "POST" });
      setStarting(null);
      setRefresh((r) => r + 1);
    } catch (e) {
      setStarting(`Analysis failed: ${(e as Error).message}`);
    }
  }

  const m = metrics.data;
  return (
    <div className="app">
      <header className="top">
        <div><h1>WorkforceIQ</h1><p className="muted">Workforce demand, capacity and skill-gap intelligence</p></div>
        <div className="run">
          {m && <span className="muted">Run <code>{m.run_id}</code> · as of {m.as_of_date} · window {m.window.start} → {m.window.end}</span>}
          <button onClick={startRun} disabled={starting?.startsWith("Running")}>{hasRun ? "Re-run analysis" : "Run analysis"}</button>
        </div>
      </header>
      {starting && <p className={starting.startsWith("Analysis failed") ? "error" : "muted"}>{starting}</p>}
      <nav className="tabs">{TABS.map((t) => <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}</nav>
      <main>
        <State loading={runs.loading || metrics.loading || names.loading} error={runs.error ?? metrics.error ?? names.error}>
          {!hasRun ? (
            <section className="card empty">
              <h3>No successful analysis run yet</h3>
              <p>Start one to compute capacity, forecasts, skill gaps, anomalies and recommendations from the database.</p>
              <button onClick={startRun}>Run analysis now</button>
            </section>
          ) : m && names.data ? (
            <>
              {tab === "Overview" && <Overview m={m} names={names.data} />}
              {tab === "Forecasting" && <Forecasting m={m} names={names.data} />}
              {tab === "Skill gaps" && <Gaps m={m} names={names.data} />}
              {tab === "Utilization" && <Utilization m={m} names={names.data} />}
              {tab === "Anomalies" && <Anomalies m={m} />}
              {tab === "Recommendations" && <Recommendations m={m} names={names.data} />}
            </>
          ) : null}
        </State>
      </main>
    </div>
  );
}
