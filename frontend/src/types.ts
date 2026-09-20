export type HealthClassification =
  | "SALUDABLE"
  | "ESTABLE"
  | "EN RIESGO"
  | "FRÁGIL"
  | "CRÍTICO"
  | "NO EVALUABLE";

export type HealthTrend = "MEJORANDO" | "ESTABLE" | "DETERIORANDO";
export type MetricTone = "positive" | "warning" | "critical" | "muted";
export type DashboardTab = "diagnosis" | "method";
export type GiroKind = "bache" | "caida_estructural" | "";

export interface SupportingMetric {
  id: string;
  label: string;
  weight: number;
  score: number | null;
  contribution: number | null;
  share: number;
  applicable: boolean;
  fact: string;
  tone: MetricTone;
}

export interface HealthScorePoint {
  period: string;
  score: number;
}

export type ForecastDirection = "up" | "down" | "flat";

export interface ForecastPoint {
  period: string;
  score: number;
  low: number;
  high: number;
}

export interface ScoreForecast {
  horizon: number;
  slope: number;
  direction: ForecastDirection;
  mae: number | null;
  p80: number;
  points: ForecastPoint[];
}

export interface HealthScorePriority {
  id: string;
  metric: string;
  score: number;
}

export interface ScoreDriver {
  id: string;
  label: string;
  points: number;
}

export interface ScoreChange {
  behavior: number | null;
  coverage: number | null;
  drivers: ScoreDriver[];
}

export interface ScoreModulator {
  label: string;
  points: number;
  fact: string;
}

export interface HealthScoreSignal {
  active: boolean;
  kind: GiroKind;
  drop: number | null;
  explanation: string;
}

export interface HealthScoreSummary {
  companyId: string;
  period: string;
  score: number;
  classification: HealthClassification;
  trend: HealthTrend;
  delta: number | null;
  confidence: "alta" | "media" | "baja";
  monthsEvaluated: number | null;
  metrics: SupportingMetric[];
  history: HealthScorePoint[];
  forecast: ScoreForecast | null;
  priorities: HealthScorePriority[];
  change: ScoreChange;
  modulator: ScoreModulator | null;
  signal: HealthScoreSignal;
}

export interface ExecutiveSummary {
  situation: string;
  treasury: string;
  limits: string;
  source: "placeholder" | "llm";
}

export interface CompanyOption {
  id: string;
  score: number | null;
  classification: HealthClassification;
}

export interface HealthScoreApiResponse {
  company_id: string;
  period: string;
  score: number;
  classification: HealthClassification;
  trend: HealthTrend;
  delta: number | null;
  confidence: "alta" | "media" | "baja";
  months_evaluated: number | null;
  metrics: SupportingMetric[];
  history: HealthScorePoint[];
  forecast: ScoreForecast | null;
  priorities: HealthScorePriority[];
  change: ScoreChange;
  modulator: ScoreModulator | null;
  signal: HealthScoreSignal;
}
