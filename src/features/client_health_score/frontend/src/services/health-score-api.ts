import type {
  CompanyOption,
  ExecutiveSummary,
  HealthScoreApiResponse,
  HealthScoreSummary,
} from "../types.js";

const KEY_STORAGE = "health_score_gemini_key";

export function readSessionApiKey(): string {
  try {
    return sessionStorage.getItem(KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function saveSessionApiKey(value: string): void {
  try {
    if (value) sessionStorage.setItem(KEY_STORAGE, value);
    else sessionStorage.removeItem(KEY_STORAGE);
  } catch {
    // Storage can be disabled; the key still works for the current request.
  }
}

export async function fetchCompanies(): Promise<CompanyOption[]> {
  const response = await fetch("/api/health-score/companies", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("No se pudo cargar el listado de empresas.");
  const data = (await response.json()) as { companies?: CompanyOption[] };
  return data.companies ?? [];
}

export async function fetchHealthScore(companyId: string): Promise<HealthScoreSummary> {
  const response = await fetch(
    `/api/health-score?company_id=${encodeURIComponent(companyId)}`,
    { headers: { Accept: "application/json" } },
  );
  if (!response.ok) throw new Error("No se pudo cargar el Health Score.");
  const data = (await response.json()) as HealthScoreApiResponse;
  return {
    companyId: data.company_id,
    period: data.period,
    score: data.score,
    classification: data.classification,
    trend: data.trend,
    delta: data.delta,
    confidence: data.confidence,
    monthsEvaluated: data.months_evaluated,
    metrics: data.metrics,
    history: data.history,
    forecast: data.forecast ?? null,
    priorities: data.priorities,
    change: data.change,
    modulator: data.modulator,
    signal: data.signal,
  };
}

export async function generateExecutiveSummary(
  companyId: string,
  apiKey: string,
): Promise<ExecutiveSummary> {
  const response = await fetch("/api/health-score/summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company_id: companyId,
      api_key: apiKey.trim(),
    }),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "No se pudo generar el resumen.");
  return {
    situation: payload.situacion || "",
    treasury: payload.tesoreria || "",
    limits: payload.limites || "",
    source: payload.fuente === "gemini" ? "llm" : "placeholder",
  };
}
