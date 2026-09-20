import { renderMethodology } from "./methodology.js";
import {
  axisAction,
  classLabel,
  classThreshold,
  deltaLine,
  giroDetail,
  giroTitle,
  signed,
  splitWhy,
  trendDetail,
  trendLabel,
} from "../data/diagnosis.js";
import type {
  DashboardTab,
  ExecutiveSummary,
  HealthScorePoint,
  HealthScoreSummary,
  ScoreForecast,
} from "../types.js";

const esc = (value: unknown): string =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

function monthShort(period: string): string {
  if (!period) return "";
  return new Intl.DateTimeFormat("es-ES", { month: "short" })
    .format(new Date(`${period}-01T00:00:00`))
    .replace(".", "");
}

function toneClass(kind: "class" | "trend" | "delta" | "giro", data: HealthScoreSummary): string {
  if (kind === "class") {
    if (data.classification === "SALUDABLE" || data.classification === "ESTABLE") return "positive";
    if (data.classification === "EN RIESGO") return "warning";
    return "critical";
  }
  if (kind === "trend" || kind === "delta") {
    if (data.trend === "DETERIORANDO" || (data.delta ?? 0) < -0.4) return "negative";
    if (data.trend === "MEJORANDO" || (data.delta ?? 0) > 0.4) return "positive";
    return "";
  }
  if (data.signal.kind === "caida_estructural") return "negative";
  if (data.signal.active) return "warning";
  return "";
}

function forecastCaption(forecast: ScoreForecast | null): string {
  if (!forecast?.points.length) return "Sin proyección: menos de 6 meses puntuados.";
  const last = forecast.points.at(-1)!;
  return `+${forecast.horizon}m ${Math.round(last.score)} [${Math.round(last.low)}–${Math.round(last.high)}] · ${signed(forecast.slope)} pts/mes`;
}

function chart(points: HealthScorePoint[], forecast: ScoreForecast | null): string {
  if (points.length < 2) return '<div class="chart-empty">Histórico no disponible</div>';
  const future = forecast?.points ?? [];
  const width = 640;
  const height = 248;
  const padX = 26;
  const padTop = 28;
  const padBottom = 42;
  const total = points.length + future.length;
  const scores = [
    ...points.map((point) => point.score),
    ...future.flatMap((point) => [point.score, point.low, point.high]),
  ];
  const min = Math.min(...scores, 33) - 3;
  const max = Math.max(...scores, 85) + 3;
  const x = (index: number) => padX + (index / Math.max(total - 1, 1)) * (width - padX * 2);
  const y = (score: number) =>
    padTop + ((max - score) / Math.max(max - min, 1)) * (height - padTop - padBottom);
  const lastIndex = points.length - 1;
  const line = points.map((point, index) => `${x(index).toFixed(1)},${y(point.score).toFixed(1)}`).join(" ");
  const area = `${x(0).toFixed(1)},${(height - padBottom).toFixed(1)} ${line} ${x(lastIndex).toFixed(1)},${(height - padBottom).toFixed(1)}`;
  const guide = (value: number) =>
    `<line x1="0" y1="${y(value).toFixed(1)}" x2="${width}" y2="${y(value).toFixed(1)}" class="chart-guide"/>`;
  const marks = points
    .map((point, index) => {
      const cx = x(index).toFixed(1);
      const cy = y(point.score);
      const last = index === lastIndex;
      return `
        <circle cx="${cx}" cy="${cy.toFixed(1)}" r="${last ? 5 : 3.5}" class="chart-dot${last ? " is-last" : ""}"/>
        <text class="chart-value" x="${cx}" y="${(cy - 12).toFixed(1)}">${Math.round(point.score)}</text>
        <text class="chart-month" x="${cx}" y="${height - 12}">${esc(monthShort(point.period))}</text>`;
    })
    .join("");

  let ray = "";
  if (future.length) {
    const xs = [lastIndex, ...future.map((_, index) => lastIndex + 1 + index)];
    const highs = [points[lastIndex].score, ...future.map((point) => point.high)];
    const lows = [points[lastIndex].score, ...future.map((point) => point.low)];
    const mid = [points[lastIndex].score, ...future.map((point) => point.score)];
    const band = [
      ...xs.map((index, i) => `${x(index).toFixed(1)},${y(highs[i]).toFixed(1)}`),
      ...[...xs].reverse().map((index, i) => `${x(index).toFixed(1)},${y(lows[lows.length - 1 - i]).toFixed(1)}`),
    ].join(" ");
    const dash = mid.map((score, i) => `${x(xs[i]).toFixed(1)},${y(score).toFixed(1)}`).join(" ");
    const futureMarks = future
      .map((point, index) => {
        const cx = x(lastIndex + 1 + index).toFixed(1);
        const cy = y(point.score);
        return `
        <circle cx="${cx}" cy="${cy.toFixed(1)}" r="3.5" class="chart-dot is-forecast"/>
        <text class="chart-value is-forecast" x="${cx}" y="${(cy - 12).toFixed(1)}">${Math.round(point.score)}</text>
        <text class="chart-month is-forecast" x="${cx}" y="${height - 12}">${esc(monthShort(point.period))}</text>`;
      })
      .join("");
    ray = `<polygon points="${band}" class="chart-forecast-band"/>
      <polyline points="${dash}" class="chart-forecast-line"/>
      ${futureMarks}`;
  }

  const direction = forecast?.direction ?? "flat";
  return `<svg class="score-chart is-${direction}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Evolución y proyección del Health Score">
    <defs><linearGradient id="score-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5c92fe" stop-opacity=".3"/><stop offset="1" stop-color="#5c92fe" stop-opacity="0"/></linearGradient></defs>
    ${guide(68)}${guide(52)}
    <polygon points="${area}" fill="url(#score-fill)"/>
    <polyline points="${line}" class="chart-line"/>
    ${ray}
    ${marks}
  </svg>`;
}

function mixBar(data: HealthScoreSummary): string {
  const parts = data.metrics.filter((item) => item.applicable && item.share > 0);
  if (!parts.length) return "";
  return `
    <div class="mix" role="img" aria-label="Composición del score">
      ${parts
        .map(
          (item) =>
            `<i class="${item.tone}" style="width:${item.share}%" title="${esc(item.label)} ${Math.round(item.score ?? 0)}"></i>`,
        )
        .join("")}
    </div>
    <div class="mix-legend">
      ${parts
        .map(
          (item) =>
            `<span><b class="${item.tone}"></b>${esc(item.label)} ${Math.round(item.score ?? 0)}</span>`,
        )
        .join("")}
    </div>`;
}

function renderDiagnosis(
  data: HealthScoreSummary,
  executive: ExecutiveSummary,
): string {
  return `
    <section class="health-hero card">
      <div class="score-overview">
        <div class="score-ring" style="--score:${data.score}">
          <div><strong>${Math.round(data.score)}</strong><span>/100</span></div>
        </div>
        <div class="score-kpis">
          <article>
            <span>Clasificación</span>
            <strong class="${toneClass("class", data)}">${esc(classLabel(data.classification))}</strong>
            <small>${esc(classThreshold(data.classification))}</small>
          </article>
          <article>
            <span>Tendencia</span>
            <strong class="${toneClass("trend", data)}">${esc(trendLabel(data.trend))}</strong>
            <small>${esc(trendDetail(data))}</small>
          </article>
          <article>
            <span>Confianza</span>
            <strong>${esc((data.confidence || "—").replace(/^\w/, (c) => c.toUpperCase()))}</strong>
            <small>${data.monthsEvaluated ? `${data.monthsEvaluated} meses evaluados` : "Cobertura incompleta"}</small>
          </article>
          <article>
            <span>Giro</span>
            <strong class="${toneClass("giro", data)}">${esc(giroTitle(data))}</strong>
            <small>${esc(giroDetail(data))}</small>
          </article>
        </div>
      </div>
      <div class="hero-mix">
        <span class="aside-label">Composición</span>
        ${mixBar(data)}
        <p class="delta-line">${esc(deltaLine(data))}</p>
      </div>
    </section>

    <section class="axis-table card" aria-label="Desglose del score">
      <div class="card-title">
        <div>
          <p class="eyebrow">Componentes</p>
          <h2>Desglose del mes</h2>
        </div>
        <span class="confidence">Peso · nota · Δ</span>
      </div>
      ${data.metrics
        .map((metric) => {
          const width = metric.applicable ? Math.max(0, Math.min(100, metric.score ?? 0)) : 0;
          return `
        <article class="axis-row ${metric.applicable ? "" : "is-off"}">
          <div class="axis-name">
            <span class="metric-tone ${metric.tone}"></span>
            <div>
              <strong>${esc(metric.label)}</strong>
              <small>${metric.weight}%</small>
            </div>
          </div>
          <div class="axis-score">
            <b>${metric.applicable ? Math.round(metric.score ?? 0) : "N/A"}</b>
            <div class="metric-bar"><i class="${metric.tone}" style="width:${width}%"></i></div>
          </div>
          <div class="axis-delta ${
            (metric.contribution ?? 0) < -0.4 ? "negative" : (metric.contribution ?? 0) > 0.4 ? "positive" : ""
          }">${signed(metric.contribution)}</div>
          <p>${esc(splitWhy(metric))}</p>
        </article>`;
        })
        .join("")}
      ${
        data.modulator
          ? `<p class="modulator-note">${esc(data.modulator.label)} ${signed(data.modulator.points)} pts · ${esc(data.modulator.fact)}</p>`
          : ""
      }
    </section>

    <section class="content-grid">
      <article class="trend-card card">
        <div class="card-title">
          <div><p class="eyebrow">Evolución</p><h2>Observado y proyección</h2></div>
          <span class="confidence">Confianza ${esc(data.confidence)}${
            data.monthsEvaluated ? ` · ${data.monthsEvaluated} meses` : ""
          }</span>
        </div>
        ${chart(data.history, data.forecast)}
        <div class="chart-footer">
          <span class="threshold"><i></i> 68 saludable · 52 estable</span>
          <span class="forecast-cap ${data.forecast?.direction || ""}">${esc(forecastCaption(data.forecast))}</span>
        </div>
      </article>

      <article class="actions-card card">
        <div class="card-title"><div><p class="eyebrow">Prioridades</p><h2>Componentes más bajos</h2></div></div>
        <ol class="priority-list">
          ${data.priorities
            .map(
              (item, index) => `<li>
                <span>${index + 1}</span>
                <div><strong>${esc(item.metric)} · ${Math.round(item.score)}</strong><p>${esc(axisAction(item.id))}</p></div>
              </li>`,
            )
            .join("")}
        </ol>
      </article>
    </section>

    <section class="summary-card card">
      <div class="summary-content">
        <div class="card-title">
          <div>
            <p class="eyebrow">Para compartir <span class="ai-tag">IA</span></p>
            <h2>${executive.source === "llm" ? "Párrafo generado" : "Redactar un párrafo"}</h2>
          </div>
          <button class="text-button" id="open-ai-settings">${executive.source === "llm" ? "Actualizar" : "Generar con IA"}</button>
        </div>
        ${
          executive.source === "llm"
            ? `<p class="summary-lead">${esc(executive.situation)}</p>
        <div class="summary-points">
          <div><span></span><p>${esc(executive.treasury)}</p></div>
          <div><span></span><p>${esc(executive.limits)}</p></div>
        </div>`
            : `<p class="summary-lead">El diagnóstico está en las cifras. Esto genera un párrafo con las mismas señales.</p>`
        }
      </div>
    </section>`;
}

export function renderDashboard(
  data: HealthScoreSummary,
  executive: ExecutiveSummary,
  tab: DashboardTab = "diagnosis",
): string {
  const month = data.period
    ? new Intl.DateTimeFormat("es-ES", {
        month: "short",
        year: "numeric",
      }).format(new Date(`${data.period}-01T00:00:00`))
    : "";

  return `
    <section class="page-heading">
      <div>
        <p class="eyebrow">Tesorería</p>
        <h1>Health Score</h1>
        <div class="view-tabs" role="tablist" aria-label="Vista del Health Score">
          <button type="button" role="tab" data-tab="diagnosis" aria-selected="${tab === "diagnosis"}">Este resultado</button>
          <button type="button" role="tab" data-tab="method" aria-selected="${tab === "method"}">Cómo se calcula</button>
        </div>
      </div>
      <div class="heading-meta">
        <span class="live-dot"></span>
        ${esc(month)}${data.monthsEvaluated ? ` · ${data.monthsEvaluated} meses` : ""}
      </div>
    </section>
    ${tab === "method" ? renderMethodology(data.metrics) : renderDiagnosis(data, executive)}`;
}
