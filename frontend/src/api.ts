import { useCallback, useEffect, useState } from "react";

// VITE_API_BASE_URL from the root .env, otherwise the Vite dev proxy (/api -> :8000).
const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface Run {
  run_id: string;
  status: "RUNNING" | "SUCCEEDED" | "FAILED";
  as_of_date: string;
  finished_at: string | null;
  error_message: string | null;
}

export interface GapGroup {
  group: string;
  rows: number;
  weeks: number;
  demand_hours: number;
  committed_hours: number;
  at_risk_hours: number;
  gap_hours: number;
  coverage_ratio: number | null;
  gap_fte: number;
  reallocated_hours: number;
  trained_hours: number;
  hire_hours: number;
  unresolved_hours: number;
  worst_severity: string;
}

export interface Metrics {
  run_id: string;
  as_of_date: string;
  window: { start: string; end: string; weeks: number };
  capacity: {
    active_employees: number;
    part_time_employees: number;
    net_hours: number;
    allocated_hours: number;
    available_hours: number;
    utilization: number | null;
    fte: { gross: number; net: number; allocated: number; available: number };
    bench_employees: number;
  };
  demand: {
    window_planned_hours: number;
    window_forecast_hours: number;
    forecast_method: string;
    duplicate_lines_excluded: number;
  };
  coverage: {
    demand_hours: number;
    committed_hours: number;
    gap_hours: number;
    at_risk_hours: number;
    coverage_ratio: number | null;
    rows_with_gap: number;
    reallocated_hours: number;
    trained_hours: number;
    hire_hours: number;
    unresolved_hours: number;
    by_severity: Record<string, number>;
  };
  findings: Record<string, Record<string, number>>;
  recommendations: {
    count: number;
    by_type: Record<string, number>;
    hours_by_type: Record<string, number>;
    hire_headcount: number;
  };
  forecast_accuracy: {
    available: boolean;
    reason: string | null;
    method: string;
    metrics: Record<string, { points: number; MAE: number | null; WAPE: number | null; BIAS: number | null }> | null;
  };
  detection_evaluation: {
    available: boolean;
    reason?: string;
    per_type?: Record<string, { tp: number; fp: number; fn: number; precision: number | null; recall: number | null; f1: number | null }>;
    micro?: { tp: number; fp: number; fn: number; precision: number | null; recall: number | null; f1: number | null };
  };
  risk_bands: Record<string, number>;
  top_gaps: GapGroup[];
  weekly: WeekPoint[];
}

export interface WeekPoint {
  week_start_date: string;
  demand_hours: number;
  forecast_hours: number;
  committed_hours: number;
  gap_hours: number;
  net_hours: number;
  allocated_hours: number;
  utilization: number | null;
}

export interface DataSummary {
  employees: { total: number };
  projects: { total: number };
}

export interface ForecastGroup {
  group: string | null;
  period: string;
  period_start: string;
  planned_hours: number;
  forecast_hours: number;
  forecast_fte: number;
}

export interface CapacityGroup {
  group: string;
  weeks: number;
  avg_headcount: number;
  gross_hours: number;
  leave_hours: number;
  training_hours: number;
  net_hours: number;
  allocated_hours: number;
  available_hours: number;
  overallocated_hours: number;
  part_time_and_partial_week_reduction_hours: number;
  utilization: number | null;
  fte_net: number;
  fte_available: number;
}

export interface CapacitySummary {
  totals: CapacityGroup | null;
  risk_bands: Record<string, number>;
  groups: CapacityGroup[];
}

export interface Finding {
  finding_id: string;
  anomaly_type: string;
  rule_id: string;
  entity_type: string;
  entity_id: string;
  week_start_date: string | null;
  related_ids: string[];
  severity: string;
  message: string;
}

export interface Recommendation {
  recommendation_id: string;
  recommendation_type: "REALLOCATE" | "TRAIN" | "HIRE";
  hire_type: string | null;
  role_id: string;
  skill_id: string;
  employee_id: string | null;
  project_id: string | null;
  period_start: string;
  period_end: string;
  hours: number;
  headcount: number | null;
  rule_ids: string[];
  explanation: string;
}

export interface Named {
  role_id?: string;
  skill_id?: string;
  project_id?: string;
  name: string;
}

export type Query = Record<string, string | number | boolean | undefined | null>;

function url(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

export async function api<T>(path: string, query: Query = {}, init?: RequestInit): Promise<T> {
  const res = await fetch(url(path, query), init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = body?.error?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

/** Every page of a paginated list (used for small reference lists: roles, skills, projects). */
export async function apiAll<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; ; page++) {
    const body = await api<Page<T>>(path, { page, page_size: 200 });
    items.push(...body.items);
    if (page >= body.pages) return items;
  }
}

export function useApi<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const run = useCallback(load, deps);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    run()
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [run]);
  return { data, error, loading };
}
