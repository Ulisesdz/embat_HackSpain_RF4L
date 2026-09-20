const AXIS_BLURBS = {
  deuda_comercial: "Pagos a proveedores sobre vencimientos. El componente de mayor peso.",
  liquidez: "Flujo operativo del trimestre relativo a ingresos.",
  colchon: "Meses de gasto cubiertos. La volatilidad del flujo reduce la nota.",
  trayectoria: "Dirección de flujo y deuda a 3 meses. No es el cambio del Health Score.",
  eficiencia: "Gasto por euro ingresado. 1,0 es el punto de equilibrio.",
  cobro_clientes: "Cobro sobre vencimientos. Pesa menos que proveedores: parte del riesgo es de contraparte.",
};

const AXIS_ACTIONS = {
  deuda_comercial: "Revisar pagos vencidos a proveedores.",
  liquidez: "Adelantar cobros o recortar salidas no operativas.",
  colchon: "Elevar caja operativa hasta un mes de gasto.",
  trayectoria: "Revertir la pendiente de flujo y de deuda comercial.",
  eficiencia: "Reducir gasto por encima de ingresos.",
  cobro_clientes: "Cobrar vencido. No adelantar pagos propios.",
};

const BANDS = [
  { min: 68, label: "Saludable" },
  { min: 52, label: "Estable" },
  { min: 42, label: "En riesgo" },
  { min: 33, label: "Frágil" },
  { min: 0, label: "Crítico" },
];

const CLASS_LABEL = {
  SALUDABLE: "Saludable",
  ESTABLE: "Estable",
  "EN RIESGO": "En riesgo",
  FRÁGIL: "Frágil",
  CRÍTICO: "Crítico",
  "NO EVALUABLE": "No evaluable",
};

const CLASS_THRESHOLD = {
  SALUDABLE: "≥ 68",
  ESTABLE: "52–67",
  "EN RIESGO": "42–51",
  FRÁGIL: "33–41",
  CRÍTICO: "< 33",
  "NO EVALUABLE": "sin evidencia",
};

const TREND_LABEL = {
  MEJORANDO: "Mejorando",
  ESTABLE: "Estable",
  DETERIORANDO: "Deteriorando",
};

const mockHealthScore = {
  companyId: "COMP_0725",
  period: "2026-08",
  score: 76.1,
  classification: "SALUDABLE",
  trend: "DETERIORANDO",
  delta: -4.8,
  confidence: "alta",
  monthsEvaluated: 20,
  metrics: [
    { id: "deuda_comercial", label: "Deuda comercial", weight: 20, score: 71.6, contribution: -2.8, share: 21.4, applicable: true, fact: "Impagos a proveedores bajos (5,7% de los vencimientos); 69% con más de 90 días", tone: "positive" },
    { id: "liquidez", label: "Liquidez", weight: 18, score: 68, contribution: -3.1, share: 18.3, applicable: true, fact: "Flujo neto ligeramente positivo (+4,0% de los ingresos)", tone: "warning" },
    { id: "colchon", label: "Colchón", weight: 18, score: 81.8, contribution: 1.8, share: 22.0, applicable: true, fact: "Colchón de flujo suficiente (+2,0 meses de gasto); caja real 9,7 meses", tone: "positive" },
    { id: "trayectoria", label: "Trayectoria", weight: 18, score: 25.6, contribution: 0, share: 6.9, applicable: true, fact: "Flujo cayendo (−6,7 pp/mes); deuda con proveedores subiendo", tone: "critical" },
    { id: "eficiencia", label: "Eficiencia", weight: 14, score: 86, contribution: 0, share: 18.0, applicable: true, fact: "Gasta 0,93x lo que ingresa (sano)", tone: "positive" },
    { id: "cobro_clientes", label: "Cobros", weight: 12, score: 47.1, contribution: -0.7, share: 8.5, applicable: true, fact: "Cobro tensionado (28,5% de los vencimientos sin cobrar)", tone: "critical" },
  ],
  history: [
    { period: "2026-01", score: 82.4 }, { period: "2026-02", score: 84.1 },
    { period: "2026-03", score: 85.8 }, { period: "2026-04", score: 84.6 },
    { period: "2026-05", score: 83.2 }, { period: "2026-06", score: 81.9 },
    { period: "2026-07", score: 80.9 }, { period: "2026-08", score: 76.1 },
  ],
  forecast: {
    horizon: 3, slope: -1.6, direction: "down", mae: 2.1, p80: 3.4,
    points: [
      { period: "2026-09", score: 74.5, low: 71.1, high: 77.9 },
      { period: "2026-10", score: 72.9, low: 67.8, high: 78.0 },
      { period: "2026-11", score: 71.3, low: 65.2, high: 77.4 },
    ],
  },
  priorities: [
    { id: "trayectoria", metric: "Trayectoria", score: 25.6 },
    { id: "cobro_clientes", metric: "Cobros", score: 47.1 },
  ],
  change: {
    behavior: -4.8,
    coverage: 0,
    drivers: [
      { id: "liquidez", label: "Liquidez", points: -3.1 },
      { id: "deuda_comercial", label: "Deuda comercial", points: -2.8 },
    ],
  },
  modulator: { label: "Apalancamiento", points: 2.4, fact: "Sin servicio de deuda ni deuda viva" },
  signal: {
    active: true,
    kind: "caida_estructural",
    drop: 12.1,
    explanation: "Su score no suele moverse, así que esta caída es un cambio real; ya hay deuda comercial vencida viva",
  },
};

const placeholderExecutiveSummary = { situation: "", treasury: "", limits: "", source: "placeholder" };

const esc = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

const classLabel = (value) => CLASS_LABEL[value] ?? value;
const classThreshold = (value) => CLASS_THRESHOLD[value] ?? "";
const trendLabel = (value) => TREND_LABEL[value] ?? value;
function trendDetail(_data) {
  return "Media 3 meses del eje Trayectoria";
}

function signed(value, digits = 1) {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value).toFixed(digits);
  if (value > 0) return `+${abs}`;
  if (value < 0) return `−${abs}`;
  return digits === 0 ? "0" : "0.0";
}

function splitWhy(metric) {
  if (!metric.applicable || metric.score == null) {
    return "Sin cobertura este mes. Excluido del cálculo.";
  }
  return metric.fact || "—";
}

function giroTitle(data) {
  if (!data.signal.active) return "Sin giro";
  if (data.signal.kind === "bache") return "Bache";
  if (data.signal.kind === "caida_estructural") return "Estructural";
  return "Giro";
}

function giroDetail(data) {
  if (!data.signal.active) return "Sin desviación vs historial";
  const drop =
    data.signal.drop == null ? "" : `${signed(-Math.abs(data.signal.drop), 0)} pts · 3 meses`;
  if (data.signal.kind === "bache") return drop ? `Rebote habitual · ${drop}` : "Rebote habitual";
  if (data.signal.kind === "caida_estructural") return drop || "Desviación vs historial";
  return drop || data.signal.explanation || "Desviación vs historial";
}

function deltaLine(data) {
  const delta = signed(data.delta);
  const drivers = (data.change?.drivers || [])
    .map((item) => `${item.label} ${signed(item.points)}`)
    .join(" · ");
  const coverage = data.change?.coverage;
  const behavior = data.change?.behavior;
  const coverageNote =
    coverage != null && behavior != null && Math.abs(coverage) > Math.abs(behavior)
      ? " · cambio atribuible a dato nuevo"
      : "";
  if (!drivers) return `Δ ${delta} vs mes anterior${coverageNote}`;
  return `Δ ${delta} = ${drivers}${coverageNote}`;
}

function monthShort(period) {
  if (!period) return "";
  return new Intl.DateTimeFormat("es-ES", { month: "short" })
    .format(new Date(`${period}-01T00:00:00`))
    .replace(".", "");
}

function toneClass(kind, data) {
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

function forecastCaption(forecast) {
  if (!forecast?.points?.length) return "Sin proyección: menos de 6 meses puntuados.";
  const last = forecast.points[forecast.points.length - 1];
  return `+${forecast.horizon}m ${Math.round(last.score)} [${Math.round(last.low)}–${Math.round(last.high)}] · ${signed(forecast.slope)} pts/mes`;
}

function chart(points, forecast) {
  if (!points || points.length < 2) return '<div class="chart-empty">Histórico no disponible</div>';
  const future = forecast?.points || [];
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
  const x = (index) => padX + (index / Math.max(total - 1, 1)) * (width - padX * 2);
  const y = (score) => padTop + ((max - score) / Math.max(max - min, 1)) * (height - padTop - padBottom);
  const lastIndex = points.length - 1;
  const line = points.map((point, index) => `${x(index).toFixed(1)},${y(point.score).toFixed(1)}`).join(" ");
  const area = `${x(0).toFixed(1)},${(height - padBottom).toFixed(1)} ${line} ${x(lastIndex).toFixed(1)},${(height - padBottom).toFixed(1)}`;
  const guide = (value) => `<line x1="0" y1="${y(value).toFixed(1)}" x2="${width}" y2="${y(value).toFixed(1)}" class="chart-guide"/>`;
  const marks = points.map((point, index) => {
    const cx = x(index).toFixed(1);
    const cy = y(point.score);
    const last = index === lastIndex;
    return `
        <circle cx="${cx}" cy="${cy.toFixed(1)}" r="${last ? 5 : 3.5}" class="chart-dot${last ? " is-last" : ""}"/>
        <text class="chart-value" x="${cx}" y="${(cy - 12).toFixed(1)}">${Math.round(point.score)}</text>
        <text class="chart-month" x="${cx}" y="${height - 12}">${esc(monthShort(point.period))}</text>`;
  }).join("");
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
    const futureMarks = future.map((point, index) => {
      const cx = x(lastIndex + 1 + index).toFixed(1);
      const cy = y(point.score);
      return `
        <circle cx="${cx}" cy="${cy.toFixed(1)}" r="3.5" class="chart-dot is-forecast"/>
        <text class="chart-value is-forecast" x="${cx}" y="${(cy - 12).toFixed(1)}">${Math.round(point.score)}</text>
        <text class="chart-month is-forecast" x="${cx}" y="${height - 12}">${esc(monthShort(point.period))}</text>`;
    }).join("");
    ray = `<polygon points="${band}" class="chart-forecast-band"/>
      <polyline points="${dash}" class="chart-forecast-line"/>
      ${futureMarks}`;
  }
  const direction = forecast?.direction || "flat";
  return `<svg class="score-chart is-${direction}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Evolución y proyección del Health Score">
    <defs><linearGradient id="score-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5c92fe" stop-opacity=".3"/><stop offset="1" stop-color="#5c92fe" stop-opacity="0"/></linearGradient></defs>
    ${guide(68)}${guide(52)}
    <polygon points="${area}" fill="url(#score-fill)"/>
    <polyline points="${line}" class="chart-line"/>
    ${ray}
    ${marks}
  </svg>`;
}

function mixBar(data) {
  const parts = data.metrics.filter((item) => item.applicable && item.share > 0);
  if (!parts.length) return "";
  return `
    <div class="mix" role="img" aria-label="Composición del score">
      ${parts.map((item) => `<i class="${item.tone}" style="width:${item.share}%" title="${esc(item.label)} ${Math.round(item.score ?? 0)}"></i>`).join("")}
    </div>
    <div class="mix-legend">
      ${parts.map((item) => `<span><b class="${item.tone}"></b>${esc(item.label)} ${Math.round(item.score ?? 0)}</span>`).join("")}
    </div>`;
}

function renderMethodology(metrics) {
  return `
    <section class="method-hero card">
      <p class="eyebrow">Metodología</p>
      <h2>0–100. Seis componentes de caja y facturas.</h2>
      <p>Media ponderada. Un mes aislado no determina el score. Sin dato, el componente se excluye.</p>
    </section>
    <section class="method-grid" aria-label="Seis componentes">
      ${metrics.map((metric) => `
        <article class="method-card card">
          <div class="method-card-head">
            <h3>${esc(metric.label)}</h3>
            <span>${metric.weight}%</span>
          </div>
          <p>${esc(AXIS_BLURBS[metric.id] || "")}</p>
        </article>`).join("")}
    </section>
    <section class="method-principles">
      <article class="card"><span>Nivel</span><strong>Clasificación</strong><p>Umbrales fijos: saludable, estable, en riesgo, frágil, crítico.</p></article>
      <article class="card"><span>Dirección</span><strong>Tendencia</strong><p>Media de 3 meses del eje Trayectoria. Independiente del 76: una empresa sana puede ir a peor.</p></article>
      <article class="card"><span>Giro</span><strong>Desviación propia</strong><p>Comparación con el historial de la misma empresa, no con el resto.</p></article>
      <article class="card"><span>Cobertura</span><strong>Dato ausente</strong><p>El componente no entra en el cálculo. La confianza del score baja.</p></article>
      <article class="card"><span>Proyección</span><strong>+3 meses</strong><p>Pendiente Theil-Sen del histórico. La banda es el p80 del error walk-forward.</p></article>
    </section>
    <section class="method-bands card">
      <div><p class="eyebrow">Umbrales</p><h2>Clasificación del score de empresa</h2></div>
      <div class="band-track" aria-hidden="true"><i class="critical"></i><i class="fragile"></i><i class="risk"></i><i class="stable"></i><i class="healthy"></i></div>
      <ul>${BANDS.map((band) => `<li><b>${band.min === 0 ? "&lt; 33" : `≥ ${band.min}`}</b> ${band.label}</li>`).join("")}</ul>
      <p class="method-note">No es un rating de crédito ni una valoración. Lee caja y facturas.</p>
    </section>`;
}

function renderDiagnosis(data, executive) {
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
        <div><p class="eyebrow">Componentes</p><h2>Desglose del mes</h2></div>
        <span class="confidence">Peso · nota · Δ</span>
      </div>
      ${data.metrics.map((metric) => {
        const width = metric.applicable ? Math.max(0, Math.min(100, metric.score ?? 0)) : 0;
        const deltaClass = (metric.contribution ?? 0) < -0.4 ? "negative" : (metric.contribution ?? 0) > 0.4 ? "positive" : "";
        return `
        <article class="axis-row ${metric.applicable ? "" : "is-off"}">
          <div class="axis-name">
            <span class="metric-tone ${metric.tone}"></span>
            <div><strong>${esc(metric.label)}</strong><small>${metric.weight}%</small></div>
          </div>
          <div class="axis-score">
            <b>${metric.applicable ? Math.round(metric.score ?? 0) : "N/A"}</b>
            <div class="metric-bar"><i class="${metric.tone}" style="width:${width}%"></i></div>
          </div>
          <div class="axis-delta ${deltaClass}">${signed(metric.contribution)}</div>
          <p>${esc(splitWhy(metric))}</p>
        </article>`;
      }).join("")}
      ${data.modulator ? `<p class="modulator-note">${esc(data.modulator.label)} ${signed(data.modulator.points)} pts · ${esc(data.modulator.fact)}</p>` : ""}
    </section>

    <section class="content-grid">
      <article class="trend-card card">
        <div class="card-title">
          <div><p class="eyebrow">Evolución</p><h2>Observado y proyección</h2></div>
          <span class="confidence">Confianza ${esc(data.confidence)}${data.monthsEvaluated ? ` · ${data.monthsEvaluated} meses` : ""}</span>
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
          ${(data.priorities || []).map((item, index) => `<li>
            <span>${index + 1}</span>
            <div><strong>${esc(item.metric)} · ${Math.round(item.score)}</strong><p>${esc(AXIS_ACTIONS[item.id] || "Revisar este componente.")}</p></div>
          </li>`).join("")}
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
        ${executive.source === "llm"
          ? `<p class="summary-lead">${esc(executive.situation)}</p>
        <div class="summary-points">
          <div><span></span><p>${esc(executive.treasury)}</p></div>
          <div><span></span><p>${esc(executive.limits)}</p></div>
        </div>`
          : `<p class="summary-lead">El diagnóstico está en las cifras. Esto genera un párrafo con las mismas señales.</p>`}
      </div>
    </section>`;
}

function renderDashboard(data, executive, tab = "diagnosis") {
  const month = data.period
    ? new Intl.DateTimeFormat("es-ES", { month: "short", year: "numeric" }).format(new Date(`${data.period}-01T00:00:00`))
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

const KEY_STORAGE = "health_score_gemini_key";
const root = document.querySelector("#health-score-root");
const dialog = document.querySelector("#ai-dialog");
const keyInput = document.querySelector("#api-key");
const generateButton = document.querySelector("#generate-summary");
const dialogStatus = document.querySelector("#dialog-status");
const companySelect = document.querySelector("#company-select");

let score = mockHealthScore;
let executive = placeholderExecutiveSummary;
let tab = "diagnosis";

function currentCompanyId() {
  return new URLSearchParams(window.location.search).get("company") || mockHealthScore.companyId;
}

function setCompanyUrl(companyId) {
  const url = new URL(window.location.href);
  url.searchParams.set("company", companyId);
  history.pushState({ company: companyId }, "", url);
}

function fillCompanies(companies, selected) {
  if (!companySelect) return;
  companySelect.innerHTML = companies.map((company) => {
    const scoreLabel = company.score == null ? "—" : String(Math.round(company.score));
    const isSelected = company.id === selected ? " selected" : "";
    return `<option value="${company.id}"${isSelected}>${company.id} · ${scoreLabel}</option>`;
  }).join("");
  companySelect.value = selected;
}

function readSessionApiKey() {
  try { return sessionStorage.getItem(KEY_STORAGE) ?? ""; } catch { return ""; }
}
function saveSessionApiKey(value) {
  try {
    if (value) sessionStorage.setItem(KEY_STORAGE, value);
    else sessionStorage.removeItem(KEY_STORAGE);
  } catch { /* ignore */ }
}

function paint() {
  if (!root) return;
  root.innerHTML = renderDashboard(score, executive, tab);
  root.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.tab === "diagnosis" || button.dataset.tab === "method") {
        tab = button.dataset.tab;
        paint();
      }
    });
  });
  document.querySelector("#open-ai-settings")?.addEventListener("click", openDialog);
  if (companySelect) companySelect.value = score.companyId;
}

function openDialog() {
  if (!dialog || !keyInput) return;
  keyInput.value = readSessionApiKey();
  dialogStatus.textContent = "";
  dialog.showModal();
  keyInput.focus();
}

async function fetchCompanies() {
  const response = await fetch("/api/health-score/companies", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("No se pudo cargar el listado de empresas.");
  const data = await response.json();
  return data.companies ?? [];
}

async function fetchHealthScore(companyId) {
  const response = await fetch(`/api/health-score?company_id=${encodeURIComponent(companyId)}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error("No se pudo cargar el Health Score.");
  const data = await response.json();
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
    forecast: data.forecast || null,
    priorities: data.priorities,
    change: data.change,
    modulator: data.modulator,
    signal: data.signal,
  };
}

async function loadCompany(companyId, pushUrl = false) {
  if (pushUrl) setCompanyUrl(companyId);
  try {
    score = await fetchHealthScore(companyId);
    executive = placeholderExecutiveSummary;
    tab = "diagnosis";
    paint();
    document.querySelector("#data-mode")?.classList.remove("visible");
  } catch {
    document.querySelector("#data-mode")?.classList.add("visible");
  }
}

async function load() {
  paint();
  const companyId = currentCompanyId();
  try {
    fillCompanies(await fetchCompanies(), companyId);
  } catch {
    fillCompanies([{ id: companyId, score: null }], companyId);
  }
  await loadCompany(companyId);
}

companySelect?.addEventListener("change", () => {
  const companyId = companySelect.value;
  if (companyId && companyId !== score.companyId) void loadCompany(companyId, true);
});
window.addEventListener("popstate", () => { void loadCompany(currentCompanyId()); });

generateButton?.addEventListener("click", async () => {
  const key = keyInput?.value.trim() || "";
  if (key) saveSessionApiKey(key);
  generateButton.disabled = true;
  generateButton.textContent = "Generando…";
  dialogStatus.textContent = "Gemini está leyendo las señales actuales.";
  try {
    const response = await fetch("/api/health-score/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ company_id: score.companyId, api_key: key }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "No se pudo generar el resumen.");
    executive = {
      situation: payload.situacion || "",
      treasury: payload.tesoreria || "",
      limits: payload.limites || "",
      source: payload.fuente === "gemini" ? "llm" : "placeholder",
    };
    tab = "diagnosis";
    paint();
    dialog?.close();
  } catch (error) {
    dialogStatus.textContent = error instanceof Error ? error.message : "No se pudo generar el resumen.";
  } finally {
    generateButton.disabled = false;
    generateButton.textContent = "Generar resumen";
  }
});

dialog?.querySelector("[data-close]")?.addEventListener("click", () => dialog.close());
dialog?.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
document.querySelector("#open-method")?.addEventListener("click", () => {
  tab = "method";
  paint();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

void load();
