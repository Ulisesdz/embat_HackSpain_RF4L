import { AXIS_BLURBS, BANDS } from "../data/recipe.js";
import type { SupportingMetric } from "../types.js";

const esc = (value: unknown): string =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

export function renderMethodology(metrics: SupportingMetric[]): string {
  return `
    <section class="method-hero card">
      <p class="eyebrow">Metodología</p>
      <h2>0–100. Seis componentes de caja y facturas.</h2>
      <p>Media ponderada. Un mes aislado no determina el score. Sin dato, el componente se excluye.</p>
    </section>

    <section class="method-grid" aria-label="Seis componentes">
      ${metrics
        .map(
          (metric) => `
        <article class="method-card card">
          <div class="method-card-head">
            <h3>${esc(metric.label)}</h3>
            <span>${metric.weight}%</span>
          </div>
          <p>${esc(AXIS_BLURBS[metric.id] || "")}</p>
        </article>`,
        )
        .join("")}
    </section>

    <section class="method-principles">
      <article class="card">
        <span>Nivel</span>
        <strong>Clasificación</strong>
        <p>Umbrales fijos: saludable, estable, en riesgo, frágil, crítico.</p>
      </article>
      <article class="card">
        <span>Dirección</span>
        <strong>Tendencia</strong>
        <p>Variación frente al mes anterior. Independiente del nivel.</p>
      </article>
      <article class="card">
        <span>Giro</span>
        <strong>Desviación propia</strong>
        <p>Comparación con el historial de la misma empresa, no con el resto.</p>
      </article>
      <article class="card">
        <span>Cobertura</span>
        <strong>Dato ausente</strong>
        <p>El componente no entra en el cálculo. La confianza del score baja.</p>
      </article>
      <article class="card">
        <span>Proyección</span>
        <strong>+3 meses</strong>
        <p>Pendiente Theil-Sen del histórico. La banda es el p80 del error walk-forward.</p>
      </article>
    </section>

    <section class="method-bands card">
      <div>
        <p class="eyebrow">Umbrales</p>
        <h2>Clasificación del score de empresa</h2>
      </div>
      <div class="band-track" aria-hidden="true">
        <i class="critical"></i><i class="fragile"></i><i class="risk"></i><i class="stable"></i><i class="healthy"></i>
      </div>
      <ul>
        ${BANDS.map((band) => `<li><b>${band.min === 0 ? "< 33" : `≥ ${band.min}`}</b> ${band.label}</li>`).join("")}
      </ul>
      <p class="method-note">No es un rating de crédito ni una valoración. Lee caja y facturas.</p>
    </section>`;
}
