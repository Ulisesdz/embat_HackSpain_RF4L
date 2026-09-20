import { AXIS_ACTIONS } from "./recipe.js";
import type { HealthScoreSummary, SupportingMetric } from "../types.js";

const CLASS_LABEL: Record<string, string> = {
  SALUDABLE: "Saludable",
  ESTABLE: "Estable",
  "EN RIESGO": "En riesgo",
  FRÁGIL: "Frágil",
  CRÍTICO: "Crítico",
  "NO EVALUABLE": "No evaluable",
};

const CLASS_THRESHOLD: Record<string, string> = {
  SALUDABLE: "≥ 68",
  ESTABLE: "52–67",
  "EN RIESGO": "42–51",
  FRÁGIL: "33–41",
  CRÍTICO: "< 33",
  "NO EVALUABLE": "sin evidencia",
};

const TREND_LABEL: Record<string, string> = {
  MEJORANDO: "Mejorando",
  ESTABLE: "Estable",
  DETERIORANDO: "Deteriorando",
};

export function classLabel(value: string): string {
  return CLASS_LABEL[value] ?? value;
}

export function classThreshold(value: string): string {
  return CLASS_THRESHOLD[value] ?? "";
}

export function trendLabel(value: string): string {
  return TREND_LABEL[value] ?? value;
}

export function trendDetail(_data: HealthScoreSummary): string {
  return "Media 3 meses del eje Trayectoria";
}

export function signed(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value).toFixed(digits);
  if (value > 0) return `+${abs}`;
  if (value < 0) return `−${abs}`;
  return digits === 0 ? "0" : "0.0";
}

export function splitWhy(metric: SupportingMetric): string {
  if (!metric.applicable || metric.score == null) {
    return "Sin cobertura este mes. Excluido del cálculo.";
  }
  return metric.fact || "—";
}

export function axisAction(id: string): string {
  return AXIS_ACTIONS[id] ?? "Revisar este componente.";
}

export function giroTitle(data: HealthScoreSummary): string {
  if (!data.signal.active) return "Sin giro";
  if (data.signal.kind === "bache") return "Bache";
  if (data.signal.kind === "caida_estructural") return "Estructural";
  return "Giro";
}

export function giroDetail(data: HealthScoreSummary): string {
  if (!data.signal.active) return "Sin desviación vs historial";
  const drop =
    data.signal.drop == null ? "" : `${signed(-Math.abs(data.signal.drop), 0)} pts · 3 meses`;
  if (data.signal.kind === "bache") return drop ? `Rebote habitual · ${drop}` : "Rebote habitual";
  if (data.signal.kind === "caida_estructural") return drop || "Desviación vs historial";
  return drop || data.signal.explanation || "Desviación vs historial";
}

export function deltaLine(data: HealthScoreSummary): string {
  const delta = signed(data.delta);
  const drivers = data.change.drivers
    .map((item) => `${item.label} ${signed(item.points)}`)
    .join(" · ");
  const coverage = data.change.coverage;
  const behavior = data.change.behavior;
  const coverageNote =
    coverage != null && behavior != null && Math.abs(coverage) > Math.abs(behavior)
      ? " · cambio atribuible a dato nuevo"
      : "";
  if (!drivers) return `Δ ${delta} vs mes anterior${coverageNote}`;
  return `Δ ${delta} = ${drivers}${coverageNote}`;
}
