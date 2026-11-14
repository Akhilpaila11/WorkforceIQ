import { ReactNode, useEffect, useState } from "react";
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

// ------------------------------------------------------------------ constants and helpers
const SECTIONS = [
  { id: "overview", label: "Overview", icon: "grid", title: "Workforce overview", sub: "Demand, capacity, gaps and data quality for the analysis window" },
  { id: "forecasting", label: "Forecasting", icon: "trend", title: "Demand forecasting", sub: "Planned versus forecast demand per period" },
  { id: "gaps", label: "Skill gaps", icon: "target", title: "Skill gaps", sub: "Coverage of demand by eligible, allocated employees" },
  { id: "utilization", label: "Utilization", icon: "gauge", title: "Capacity & utilization", sub: "Net capacity after part-time schedules, leave and training" },
  { id: "anomalies", label: "Anomalies", icon: "alert", title: "Anomaly detection", sub: "Data-quality exceptions found by the business rules" },
  { id: "recommendations", label: "Recommendations", icon: "bulb", title: "Recommendations", sub: "Reallocate, train or hire to close the remaining gaps" },
] as const;
type SectionId = (typeof SECTIONS)[number]["id"];

const ANOMALIES: Record<string, { label: string; rule: string }> = {
  ALLOCATION_EXCEEDS_AVAILABILITY: { label: "Allocation exceeds availability", rule: "BR-UTL-004" },
  EXPIRED_SKILL_TREATED_AS_CURRENT: { label: "Expired skill treated as current", rule: "BR-SKL-004" },
  DUPLICATE_DEMAND: { label: "Duplicate project demand", rule: "BR-DEM-004" },
  OVERLAPPING_ALLOCATION_CONFLICT: { label: "Overlapping assignment conflict", rule: "BR-ALC-003" },
  STALE_SKILL: { label: "Stale skill (informational)", rule: "BR-SKL-002" },
};
const REQUIRED = Object.keys(ANOMALIES).filter((k) => k !== "STALE_SKILL");
const BANDS = ["UNDER_UTILIZED", "HEALTHY", "HIGH", "OVERALLOCATED", "UNAVAILABLE"];

const num = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
const label = (v: string) => v.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

type Names = { roles: Record<string, string>; skills: Record<string, string>; projects: Record<string, string> };

// ------------------------------------------------------------------ small building blocks
const ICONS: Record<string, string> = {
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  trend: "M3 17l6-6 4 4 8-8M15 7h6v6",
  target: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0 4a1 1 0 1 0 0 2 1 1 0 0 0 0-2z",
  gauge: "M4 18a8 8 0 1 1 16 0M12 18l4-6",
  alert: "M12 3l9 16H3zM12 10v4M12 17v.5",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3z",
  users: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8",
  folder: "M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 3",
  play: "M7 4l12 8-12 8z",
};

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d={ICONS[name]} />
    </svg>
  );
}

function State({ loading, error, empty, children }: { loading: boolean; error: string | null; empty?: boolean; children: ReactNode }) {
  if (loading) return <div className="state"><span className="spinner" /> Loading data…</div>;
  if (error) return <div className="state error"><Icon name="alert" /> Could not load data: {error}</div>;
  if (empty) return <div className="state">No data for this selection.</div>;
  return <>{children}</>;
}

function Kpi({ icon, tone, label: text, value, hint }: { icon: string; tone: string; label: string; value: string; hint?: string }) {
  return (
    <div className="kpi">
      <div className={`kpi-icon t-${tone}`}><Icon name={icon} /></div>
      <div>
        <span className="kpi-label">{text}</span>
        <strong className="kpi-value">{value}</strong>
        {hint && <small className="kpi-hint">{hint}</small>}
      </div>
    </div>
  );
}

function Card({ title, sub, action, children, className = "" }: { title?: string; sub?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          <div>{title && <h3>{title}</h3>}{sub && <p className="muted">{sub}</p>}</div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

function Badge({ value }: { value: string }) {
  return <span className={`badge b-${value.toLowerCase()}`}>{label(value)}</span>;
}

function Meter({ value, tone = "blue" }: { value: number | null; tone?: string }) {
  return <span className="meter"><i className={`t-${tone}`} style={{ width: pct(Math.min(1, Math.max(0, value ?? 0))) }} /></span>;
}

function Pager<T>({ page, onPage }: { page: Page<T>; onPage: (p: number) => void }) {
  return (
    <div className="pager">
      <span className="muted">{num(page.total)} rows{page.pages > 1 ? ` · page ${page.page} of ${page.pages}` : ""}</span>
      {page.pages > 1 && (
        <div>
          <button className="btn" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>‹ Previous</button>
          <button className="btn" disabled={page.page >= page.pages} onClick={() => onPage(page.page + 1)}>Next ›</button>
        </div>
      )}
    </div>
  );
}

/** Stacked horizontal bar of named parts (values from the API). */
function Stack({ parts }: { parts: { name: string; value: number; tone: string }[] }) {
  const total = sum(parts.map((p) => p.value)) || 1;
  return (
    <>
      <div className="stack">{parts.map((p) => p.value > 0 && <i key={p.name} className={`t-${p.tone}`} style={{ width: `${(p.value / total) * 100}%` }} title={`${p.name}: ${num(p.value)}`} />)}</div>
      <ul className="legend-list">
        {parts.map((p) => (
          <li key={p.name}><span className={`dot t-${p.tone}`} />{p.name}<b>{num(p.value)}</b><span className="muted">{pct(p.value / total)}</span></li>
        ))}
      </ul>
    </>
  );
}

// ------------------------------------------------------------------ SVG combo chart
type Series = { name: string; values: number[]; tone: string; dashed?: boolean };

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return ([1, 2, 2.5, 5, 10].find((m) => m * p >= v) ?? 10) * p;
}

function ComboChart({ labels, bars, lines }: { labels: string[]; bars: Series[]; lines: Series[] }) {
  const w = 820, h = 280, left = 56, right = 16, top = 16, bottom = 36;
  const max = niceMax(Math.max(0, ...bars.flatMap((s) => s.values), ...lines.flatMap((s) => s.values)));
  const step = (w - left - right) / Math.max(1, labels.length);
  const y = (v: number) => top + (1 - v / max) * (h - top - bottom);
  const x = (i: number) => left + step * i + step / 2;
  const barW = Math.min(36, (step * 0.7) / Math.max(1, bars.length));
  const every = Math.ceil(labels.length / 14);
  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        {[...bars, ...lines].map((s) => <span key={s.name}><i className={`key t-${s.tone} ${lines.includes(s) ? "line" : ""} ${s.dashed ? "dashed" : ""}`} />{s.name}</span>)}
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="chart" role="img" aria-label={[...bars, ...lines].map((s) => s.name).join(", ")}>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={left} x2={w - right} y1={y(max * f)} y2={y(max * f)} className="gridline" />
            <text x={left - 8} y={y(max * f) + 4} className="axis" textAnchor="end">{num(max * f)}</text>
          </g>
        ))}
        {labels.map((l, i) => (
          <g key={l}>
            {bars.map((s, b) => {
              const v = s.values[i] ?? 0;
              return (
                <rect key={s.name} x={x(i) - (barW * bars.length) / 2 + b * barW} y={y(v)} width={barW - 2} height={Math.max(0, h - bottom - y(v))} rx={3} className={`fill-${s.tone}`}>
                  <title>{`${l} · ${s.name}: ${num(v)} h`}</title>
                </rect>
              );
            })}
            {i % every === 0 && <text x={x(i)} y={h - bottom + 18} className="axis" textAnchor="middle">{l}</text>}
          </g>
        ))}
        {lines.map((s) => (
          <g key={s.name}>
            <polyline points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} className={`stroke-${s.tone} ${s.dashed ? "dashed" : ""}`} fill="none" />
            {s.values.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={3.5} className={`fill-${s.tone}`}><title>{`${labels[i]} · ${s.name}: ${num(v)} h`}</title></circle>)}
          </g>
        ))}
      </svg>
    </div>
  );
}

// ------------------------------------------------------------------ reference names
function useNames() {
  return useApi(async () => {
    const [roles, skills, projects] = await Promise.all([apiAll<Named>("/roles"), apiAll<Named>("/skills"), apiAll<Named>("/projects")]);
    const map = (rows: Named[], key: keyof Named) => Object.fromEntries(rows.map((r) => [r[key] as string, r.name]));
    return { roles: map(roles, "role_id"), skills: map(skills, "skill_id"), projects: map(projects, "project_id") };
  }, []);
}

// ------------------------------------------------------------------ overview
function Overview({ m, names }: { m: Metrics; names: Names }) {
  const summary = useApi(() => api<DataSummary>("/dashboard/summary"), []);
  const exceptions = sum(REQUIRED.map((k) => sum(Object.values(m.findings[k] ?? {}))));
  const c = m.coverage;
  const fa = m.forecast_accuracy;
  const prw = fa.metrics?.PROJECT_ROLE_WEEK;
  const de = m.detection_evaluation;
  const weeks = m.weekly.map((w) => w.week_start_date.slice(5));
  return (
    <>
      <div className="kpis">
        <Kpi icon="users" tone="indigo" label="Employees" value={summary.data ? num(summary.data.employees.total) : "…"} hint={`${num(m.capacity.active_employees)} active · ${num(m.capacity.part_time_employees)} part-time`} />
        <Kpi icon="folder" tone="blue" label="Projects" value={summary.data ? num(summary.data.projects.total) : "…"} hint={`${num(m.demand.duplicate_lines_excluded)} duplicate lines excluded`} />
        <Kpi icon="trend" tone="violet" label="Demand (window)" value={`${num(m.demand.window_planned_hours)} h`} hint={`Forecast ${num(m.demand.window_forecast_hours)} h`} />
        <Kpi icon="clock" tone="teal" label="Net capacity" value={`${num(m.capacity.net_hours)} h`} hint={`${num(m.capacity.fte.net, 1)} FTE · ${num(m.capacity.available_hours)} h free`} />
        <Kpi icon="gauge" tone="green" label="Utilization" value={pct(m.capacity.utilization)} hint={`${num(m.capacity.bench_employees)} employees on bench`} />
        <Kpi icon="target" tone="orange" label="Skill gap" value={`${num(c.gap_hours)} h`} hint={`Coverage ${pct(c.coverage_ratio)}`} />
        <Kpi icon="alert" tone="red" label="Exceptions" value={num(exceptions)} hint="4 anomaly types" />
        <Kpi icon="bulb" tone="amber" label="Recommendations" value={num(m.recommendations.count)} hint={`Hire ${num(m.recommendations.hire_headcount)} · train ${num(m.recommendations.by_type.TRAIN ?? 0)}`} />
      </div>

      <Card title="Demand vs forecast vs capacity" sub={`Weekly hours, ${m.window.start} → ${m.window.end} (forecast: ${m.demand.forecast_method})`}>
        <State loading={false} error={null} empty={!m.weekly.length}>
          <ComboChart
            labels={weeks}
            bars={[{ name: "Planned demand", values: m.weekly.map((w) => w.demand_hours), tone: "indigo" }, { name: "Committed coverage", values: m.weekly.map((w) => w.committed_hours), tone: "teal" }]}
            lines={[{ name: "Forecast demand", values: m.weekly.map((w) => w.forecast_hours), tone: "orange" }, { name: "Net capacity", values: m.weekly.map((w) => w.net_hours), tone: "slate", dashed: true }]}
          />
        </State>
      </Card>

      <div className="cols">
        <Card title="Utilization breakdown" sub="Employee-weeks in the window by risk band (BR-UTL-002)">
          <Stack parts={BANDS.filter((b) => m.risk_bands[b] != null).map((b) => ({ name: label(b), value: m.risk_bands[b], tone: bandTone(b) }))} />
        </Card>
        <Card title="Skill-gap breakdown" sub="Demand hours: covered, resolved by recommendations, unresolved">
          <Stack
            parts={[
              { name: "Committed", value: c.committed_hours, tone: "teal" },
              { name: "Reallocate", value: c.reallocated_hours, tone: "blue" },
              { name: "Train", value: c.trained_hours, tone: "violet" },
              { name: "Hire", value: c.hire_hours, tone: "orange" },
              { name: "Unresolved", value: c.unresolved_hours, tone: "red" },
            ]}
          />
        </Card>
      </div>

      <div className="cols">
        <Card title="Top skill gaps" sub="Role · primary skill, ranked by gap hours">
          <GapTable rows={m.top_gaps} names={names} />
        </Card>
        <Card title="Anomaly summary" sub="Findings in this run, by severity">
          <ul className="anomaly-list">
            {REQUIRED.map((k) => {
              const bySeverity = m.findings[k] ?? {};
              return (
                <li key={k}>
                  <div><b>{ANOMALIES[k].label}</b><span className="muted">{ANOMALIES[k].rule}</span></div>
                  <div className="chips">
                    {Object.keys(bySeverity).length
                      ? Object.entries(bySeverity).map(([s, n]) => <span key={s} className={`badge b-${s.toLowerCase()}`}>{label(s)} {n}</span>)
                      : <span className="muted">none</span>}
                  </div>
                  <strong>{num(sum(Object.values(bySeverity)))}</strong>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      <Card title="Model quality" sub="Measured on data the models did not see">
        <div className="quality">
          <div>
            <h4>Forecast accuracy · {fa.method}</h4>
            {fa.available && prw ? (
              <div className="metric-row">
                <div className="metric"><span>WAPE</span><strong>{pct(prw.WAPE)}</strong><small>weighted abs. % error</small></div>
                <div className="metric"><span>MAE</span><strong>{num(prw.MAE, 1)} h</strong><small>per project-role-week</small></div>
                <div className="metric"><span>Bias</span><strong>{pct(prw.BIAS)}</strong><small>{num(prw.points)} hold-out points</small></div>
              </div>
            ) : (
              <p className="muted">Not available — {fa.reason}</p>
            )}
          </div>
          <div>
            <h4>Anomaly detection vs ground truth</h4>
            {de.available && de.per_type ? (
              <table className="compact">
                <thead><tr><th>Type</th><th className="r">TP</th><th className="r">FP</th><th className="r">FN</th><th className="r">Precision</th><th className="r">Recall</th><th className="r">F1</th></tr></thead>
                <tbody>
                  {Object.entries(de.per_type).map(([k, v]) => (
                    <tr key={k}><td>{ANOMALIES[k]?.label ?? k}</td><td className="r">{v.tp}</td><td className="r">{v.fp}</td><td className="r">{v.fn}</td><td className="r">{pct(v.precision)}</td><td className="r">{pct(v.recall)}</td><td className="r"><span className="pill">{pct(v.f1)}</span></td></tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">Not available — {de.reason}</p>
            )}
          </div>
        </div>
      </Card>
    </>
  );
}

function bandTone(band: string) {
  return { UNDER_UTILIZED: "slate", HEALTHY: "green", HIGH: "amber", OVERALLOCATED: "red", UNAVAILABLE: "gray" }[band] ?? "blue";
}

// ------------------------------------------------------------------ forecasting
function Forecasting({ m, names }: { m: Metrics; names: Names }) {
  const [project, setProject] = useState("");
  const [role, setRole] = useState("");
  const [period, setPeriod] = useState("week");
  const data = useApi(
    () => api<Page<ForecastGroup>>("/forecasts/summary", { run_id: m.run_id, group_by: "total", period, project_id: project, role_id: role, page_size: 200 }),
    [m.run_id, project, role, period],
  );
  const rows = data.data?.items ?? [];
  const planned = sum(rows.map((r) => r.planned_hours));
  const forecast = sum(rows.map((r) => r.forecast_hours));
  return (
    <>
      <div className="toolbar">
        <label>Project<select value={project} onChange={(e) => setProject(e.target.value)}><option value="">All projects</option>{Object.entries(names.projects).map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></label>
        <label>Role<select value={role} onChange={(e) => setRole(e.target.value)}><option value="">All roles</option>{Object.entries(names.roles).map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select></label>
        <label>Period<select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="week">Week</option><option value="month">Month</option></select></label>
      </div>
      <State loading={data.loading} error={data.error} empty={!rows.length}>
        <div className="kpis three">
          <Kpi icon="trend" tone="indigo" label="Planned demand" value={`${num(planned)} h`} hint="Counted, de-duplicated lines" />
          <Kpi icon="trend" tone="orange" label={`Forecast (${m.demand.forecast_method})`} value={`${num(forecast)} h`} hint={`${num(forecast / (40 * Math.max(1, rows.length)), 1)} FTE per ${period}`} />
          <Kpi icon="gauge" tone="violet" label="Forecast vs plan" value={planned ? pct(forecast / planned - 1) : "—"} hint="Positive = more than planned" />
        </div>
        <Card title="Planned vs forecast demand" sub={`Hours per ${period} from ${m.window.start}`}>
          <ComboChart labels={rows.map((r) => r.period)} bars={[{ name: "Planned", values: rows.map((r) => r.planned_hours), tone: "indigo" }]} lines={[{ name: "Forecast", values: rows.map((r) => r.forecast_hours), tone: "orange" }]} />
        </Card>
        <Card title="Forecast table">
          <table>
            <thead><tr><th>Period</th><th className="r">Planned h</th><th className="r">Forecast h</th><th className="r">Difference</th><th className="r">Forecast FTE</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.period}><td>{r.period}</td><td className="r">{num(r.planned_hours)}</td><td className="r">{num(r.forecast_hours)}</td><td className="r">{num(r.forecast_hours - r.planned_hours)}</td><td className="r">{num(r.forecast_fte, 1)}</td></tr>)}</tbody>
          </table>
        </Card>
      </State>
    </>
  );
}

// ------------------------------------------------------------------ skill gaps
function GapTable({ rows, names }: { rows: GapGroup[]; names: Names }) {
  if (!rows.length) return <div className="state">No skill gaps in this run.</div>;
  return (
    <table>
      <thead><tr><th>Role</th><th>Skill</th><th className="r">Demand h</th><th>Coverage</th><th className="r">Gap h</th><th className="r">Gap FTE</th><th>Severity</th></tr></thead>
      <tbody>
        {rows.map((g) => {
          const [role, skill] = g.group.split("|");
          return (
            <tr key={g.group}>
              <td>{names.roles[role] ?? role}</td><td>{names.skills[skill] ?? skill}</td><td className="r">{num(g.demand_hours)}</td>
              <td className="nowrap"><Meter value={g.coverage_ratio} tone={(g.coverage_ratio ?? 0) >= 0.75 ? "green" : (g.coverage_ratio ?? 0) >= 0.5 ? "amber" : "red"} /> {pct(g.coverage_ratio, 0)}</td>
              <td className="r"><b>{num(g.gap_hours)}</b></td><td className="r">{num(g.gap_fte, 1)}</td><td><Badge value={g.worst_severity} /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Gaps({ m, names }: { m: Metrics; names: Names }) {
  const [page, setPage] = useState(1);
  const data = useApi(() => api<Page<GapGroup>>("/gap-analysis/summary", { run_id: m.run_id, group_by: "role_skill", only_gaps: true, page, page_size: 20 }), [m.run_id, page]);
  const c = m.coverage;
  return (
    <>
      <div className="kpis">
        <Kpi icon="trend" tone="indigo" label="Demand" value={`${num(c.demand_hours)} h`} hint="Analysis window" />
        <Kpi icon="users" tone="teal" label="Committed" value={`${num(c.committed_hours)} h`} hint={`Coverage ${pct(c.coverage_ratio)}`} />
        <Kpi icon="alert" tone="amber" label="At risk" value={`${num(c.at_risk_hours)} h`} hint="Allocated but not eligible" />
        <Kpi icon="target" tone="red" label="Gap" value={`${num(c.gap_hours)} h`} hint={`${num(c.unresolved_hours)} h unresolved after actions`} />
      </div>
      <Card title="Gaps by role and skill" sub="Only rows with a gap; ratios recomputed from summed hours (BR-GAP-007)">
        <State loading={data.loading} error={data.error} empty={!data.data?.items.length}>
          {data.data && <><GapTable rows={data.data.items} names={names} /><Pager page={data.data} onPage={setPage} /></>}
        </State>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ utilization
function riskOf(u: number | null) {
  return u == null ? "UNAVAILABLE" : u > 1 ? "OVERALLOCATED" : u >= 0.85 ? "HIGH" : u >= 0.5 ? "HEALTHY" : "UNDER_UTILIZED";
}

function Utilization({ m, names }: { m: Metrics; names: Names }) {
  const weeks = useApi(() => api<CapacitySummary>("/capacity/summary", { run_id: m.run_id, group_by: "week" }), [m.run_id]);
  const roles = useApi(() => api<CapacitySummary>("/capacity/summary", { run_id: m.run_id, group_by: "role", date_from: m.window.start }), [m.run_id]);
  const t = weeks.data?.totals;
  const groups = weeks.data?.groups ?? [];
  return (
    <State loading={weeks.loading || roles.loading} error={weeks.error ?? roles.error} empty={!t}>
      {t && (
        <>
          <div className="kpis three">
            <Kpi icon="clock" tone="indigo" label="Gross hours" value={num(t.gross_hours)} hint={`Part-time & partial weeks −${num(t.part_time_and_partial_week_reduction_hours)} h`} />
            <Kpi icon="users" tone="slate" label="Leave / training" value={`${num(t.leave_hours)} / ${num(t.training_hours)}`} hint="Hours deducted" />
            <Kpi icon="clock" tone="teal" label="Net capacity" value={`${num(t.net_hours)} h`} hint={`${num(t.fte_net, 1)} FTE`} />
            <Kpi icon="folder" tone="blue" label="Allocated" value={`${num(t.allocated_hours)} h`} hint={`Over-allocated ${num(t.overallocated_hours)} h`} />
            <Kpi icon="target" tone="green" label="Available" value={`${num(t.available_hours)} h`} hint={`${num(t.fte_available, 1)} FTE free`} />
            <Kpi icon="gauge" tone="violet" label="Utilization" value={pct(t.utilization)} hint={`All ${t.weeks} weeks · window ${pct(m.capacity.utilization)}`} />
          </div>
          <Card title="Weekly capacity and allocation" sub="Hours per week across the horizon">
            <ComboChart labels={groups.map((g) => g.group.slice(5))} bars={[{ name: "Net capacity", values: groups.map((g) => g.net_hours), tone: "teal" }, { name: "Allocated", values: groups.map((g) => g.allocated_hours), tone: "indigo" }]} lines={[]} />
          </Card>
          <div className="cols">
            <Card title="Risk bands" sub="Employee-weeks in the analysis window">
              <Stack parts={BANDS.filter((b) => m.risk_bands[b] != null).map((b) => ({ name: label(b), value: m.risk_bands[b], tone: bandTone(b) }))} />
            </Card>
            <Card title="Utilization by role" sub="Analysis window">
              <table>
                <thead><tr><th>Role</th><th className="r">Net h</th><th className="r">Allocated h</th><th>Utilization</th></tr></thead>
                <tbody>{roles.data?.groups.map((g) => (
                  <tr key={g.group}><td>{names.roles[g.group] ?? g.group}</td><td className="r">{num(g.net_hours)}</td><td className="r">{num(g.allocated_hours)}</td>
                    <td className="nowrap"><Meter value={g.utilization} tone={bandTone(riskOf(g.utilization))} /> {pct(g.utilization)}</td></tr>
                ))}</tbody>
              </table>
            </Card>
          </div>
          <Card title="Weekly detail">
            <table>
              <thead><tr><th>Week</th><th className="r">Headcount</th><th className="r">Net h</th><th className="r">Allocated h</th><th>Utilization</th><th>Risk</th></tr></thead>
              <tbody>{groups.map((g) => (
                <tr key={g.group} className={g.group >= m.window.start ? "" : "past"}>
                  <td>{g.group}{g.group === m.window.start && <span className="tag">as-of</span>}</td><td className="r">{num(g.avg_headcount)}</td><td className="r">{num(g.net_hours)}</td><td className="r">{num(g.allocated_hours)}</td>
                  <td className="nowrap"><Meter value={g.utilization} tone={bandTone(riskOf(g.utilization))} /> {pct(g.utilization)}</td><td><Badge value={riskOf(g.utilization)} /></td>
                </tr>
              ))}</tbody>
            </table>
          </Card>
        </>
      )}
    </State>
  );
}

// ------------------------------------------------------------------ anomalies
function Anomalies({ m }: { m: Metrics }) {
  const [type, setType] = useState(REQUIRED[0]);
  const [page, setPage] = useState(1);
  const data = useApi(() => api<Page<Finding>>("/exceptions", { run_id: m.run_id, anomaly_type: type, page, page_size: 20 }), [m.run_id, type, page]);
  return (
    <>
      <div className="kpis">
        {Object.entries(ANOMALIES).map(([k, a]) => {
          const bySeverity = m.findings[k] ?? {};
          return (
            <button key={k} className={`kpi pick ${type === k ? "on" : ""}`} onClick={() => { setType(k); setPage(1); }}>
              <div className={`kpi-icon t-${k === "STALE_SKILL" ? "slate" : "red"}`}><Icon name="alert" /></div>
              <div>
                <span className="kpi-label">{a.label}</span>
                <strong className="kpi-value">{num(sum(Object.values(bySeverity)))}</strong>
                <small className="kpi-hint">{a.rule} · {Object.entries(bySeverity).map(([s, n]) => `${label(s)} ${n}`).join(", ") || "none"}</small>
              </div>
            </button>
          );
        })}
      </div>
      <Card title={ANOMALIES[type].label} sub={`Detected by ${ANOMALIES[type].rule} from source records — never from ground-truth labels`}>
        <State loading={data.loading} error={data.error} empty={!data.data?.items.length}>
          {data.data && (
            <>
              <table>
                <thead><tr><th>Severity</th><th>Record</th><th>Week</th><th>Related records</th><th>Explanation</th></tr></thead>
                <tbody>{data.data.items.map((f) => (
                  <tr key={f.finding_id}>
                    <td><Badge value={f.severity} /></td>
                    <td className="nowrap"><span className="muted">{f.entity_type}</span><br /><code>{f.entity_id}</code></td>
                    <td className="nowrap">{f.week_start_date ?? "—"}</td>
                    <td className="ids">{f.related_ids.map((id) => <code key={id}>{id}</code>)}</td>
                    <td>{f.message}</td>
                  </tr>
                ))}</tbody>
              </table>
              <Pager page={data.data} onPage={setPage} />
            </>
          )}
        </State>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ recommendations
function Recommendations({ m, names }: { m: Metrics; names: Names }) {
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const data = useApi(() => api<Page<Recommendation>>("/recommendations", { run_id: m.run_id, recommendation_type: type, page, page_size: 15 }), [m.run_id, type, page]);
  const r = m.recommendations;
  const options = [
    { id: "", name: "All actions", icon: "bulb", tone: "indigo", count: r.count, hours: sum(Object.values(r.hours_by_type)) },
    { id: "REALLOCATE", name: "Reallocate", icon: "users", tone: "green", count: r.by_type.REALLOCATE ?? 0, hours: r.hours_by_type.REALLOCATE ?? 0 },
    { id: "TRAIN", name: "Train", icon: "trend", tone: "violet", count: r.by_type.TRAIN ?? 0, hours: r.hours_by_type.TRAIN ?? 0 },
    { id: "HIRE", name: "Hire", icon: "folder", tone: "orange", count: r.by_type.HIRE ?? 0, hours: r.hours_by_type.HIRE ?? 0 },
  ];
  return (
    <>
      <div className="kpis">
        {options.map((o) => (
          <button key={o.name} className={`kpi pick ${type === o.id ? "on" : ""}`} onClick={() => { setType(o.id); setPage(1); }}>
            <div className={`kpi-icon t-${o.tone}`}><Icon name={o.icon} /></div>
            <div>
              <span className="kpi-label">{o.name}</span>
              <strong className="kpi-value">{num(o.count)}</strong>
              <small className="kpi-hint">{num(o.hours)} h{o.id === "HIRE" ? ` · ${num(r.hire_headcount)} people` : ""}</small>
            </div>
          </button>
        ))}
      </div>
      <Card title="Actions" sub="Ordered by rank; every action lists the business rules and the reasoning behind it">
        <State loading={data.loading} error={data.error} empty={!data.data?.items.length}>
          {data.data && (
            <>
              <div className="recs">{data.data.items.map((x) => (
                <article key={x.recommendation_id} className={`rec r-${x.recommendation_type.toLowerCase()}`}>
                  <header>
                    <Badge value={x.recommendation_type} />
                    <b>{names.roles[x.role_id] ?? x.role_id} · {names.skills[x.skill_id] ?? x.skill_id}</b>
                    <span className="rec-hours">{num(x.hours, 1)} h</span>
                  </header>
                  <div className="rec-meta muted">
                    {x.employee_id ? <span>Employee <code>{x.employee_id}</code></span> : <span>{x.headcount} × {label(x.hire_type ?? "")} hire</span>}
                    {x.project_id && <span>Project {names.projects[x.project_id] ?? x.project_id}</span>}
                    <span>{x.period_start} → {x.period_end}</span>
                  </div>
                  <p>{x.explanation}</p>
                  <small className="muted">{x.recommendation_id} · {x.rule_ids.join(" · ")}</small>
                </article>
              ))}</div>
              <Pager page={data.data} onPage={setPage} />
            </>
          )}
        </State>
      </Card>
    </>
  );
}

// ------------------------------------------------------------------ shell
function currentSection(): SectionId {
  const id = window.location.hash.slice(1);
  return (SECTIONS.find((s) => s.id === id)?.id ?? "overview") as SectionId;
}

export default function App() {
  const [section, setSection] = useState<SectionId>(currentSection);
  const [refresh, setRefresh] = useState(0);
  const [starting, setStarting] = useState<string | null>(null);
  const runs = useApi(() => api<Page<Run>>("/analysis/runs", { status: "SUCCEEDED", page_size: 1 }), [refresh]);
  const hasRun = (runs.data?.total ?? 0) > 0;
  const metrics = useApi(() => (hasRun ? api<Metrics>("/dashboard/metrics") : Promise.resolve(null)), [hasRun, refresh]);
  const names = useNames();
  useEffect(() => {
    const onHash = () => setSection(currentSection());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  async function startRun() {
    setStarting("running");
    try {
      await api<Run>("/analysis/runs", {}, { method: "POST" });
      setStarting(null);
      setRefresh((r) => r + 1);
    } catch (e) {
      setStarting(`Analysis failed: ${(e as Error).message}`);
    }
  }

  const m = metrics.data;
  const meta = SECTIONS.find((s) => s.id === section)!;
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand"><span className="logo">W</span><div><b>WorkforceIQ</b><small>Workforce intelligence</small></div></div>
        <nav>
          {SECTIONS.map((s) => (
            <a key={s.id} href={`#${s.id}`} className={s.id === section ? "on" : ""}><Icon name={s.icon} /><span>{s.label}</span></a>
          ))}
        </nav>
        {m && (
          <div className="run-box">
            <span className="status-dot ok" /> Latest run
            <code>{m.run_id}</code>
            <small>As of {m.as_of_date}</small>
            <small>Window {m.window.start} → {m.window.end}</small>
          </div>
        )}
      </aside>
      <div className="main">
        <header className="page-head">
          <div><h1>{meta.title}</h1><p className="muted">{meta.sub}</p></div>
          <button className="btn primary" onClick={startRun} disabled={starting === "running"}>
            <Icon name="play" size={14} /> {starting === "running" ? "Running analysis…" : hasRun ? "Re-run analysis" : "Run analysis"}
          </button>
        </header>
        {starting && starting !== "running" && <div className="state error">{starting}</div>}
        <State loading={runs.loading || metrics.loading || names.loading} error={runs.error ?? metrics.error ?? names.error}>
          {!hasRun ? (
            <section className="card empty">
              <div className="kpi-icon t-indigo big"><Icon name="play" size={26} /></div>
              <h3>No successful analysis run yet</h3>
              <p className="muted">Start one to compute capacity, forecasts, skill gaps, anomalies and recommendations from the database.</p>
              <button className="btn primary" onClick={startRun} disabled={starting === "running"}>{starting === "running" ? "Running analysis…" : "Run analysis now"}</button>
            </section>
          ) : m && names.data ? (
            <>
              {section === "overview" && <Overview m={m} names={names.data} />}
              {section === "forecasting" && <Forecasting m={m} names={names.data} />}
              {section === "gaps" && <Gaps m={m} names={names.data} />}
              {section === "utilization" && <Utilization m={m} names={names.data} />}
              {section === "anomalies" && <Anomalies m={m} />}
              {section === "recommendations" && <Recommendations m={m} names={names.data} />}
            </>
          ) : null}
        </State>
      </div>
    </div>
  );
}
