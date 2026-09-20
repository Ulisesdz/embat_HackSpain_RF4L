import { renderDashboard } from "./components/health-score-summary.js";
import {
  mockHealthScore,
  placeholderExecutiveSummary,
} from "./data/mock-health-score.js";
import {
  fetchCompanies,
  fetchHealthScore,
  generateExecutiveSummary,
  readSessionApiKey,
  saveSessionApiKey,
} from "./services/health-score-api.js";
import type { CompanyOption, DashboardTab, ExecutiveSummary, HealthScoreSummary } from "./types.js";

const root = document.querySelector<HTMLElement>("#health-score-root");
const dialog = document.querySelector<HTMLDialogElement>("#ai-dialog");
const keyInput = document.querySelector<HTMLInputElement>("#api-key");
const generateButton = document.querySelector<HTMLButtonElement>("#generate-summary");
const dialogStatus = document.querySelector<HTMLElement>("#dialog-status");
const companySelect = document.querySelector<HTMLSelectElement>("#company-select");

let score: HealthScoreSummary = mockHealthScore;
let executive: ExecutiveSummary = placeholderExecutiveSummary;
let tab: DashboardTab = "diagnosis";

function currentCompanyId(): string {
  return new URLSearchParams(window.location.search).get("company") || mockHealthScore.companyId;
}

function setCompanyUrl(companyId: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set("company", companyId);
  history.pushState({ company: companyId }, "", url);
}

function fillCompanies(companies: CompanyOption[], selected: string): void {
  if (!companySelect) return;
  companySelect.innerHTML = companies
    .map((company) => {
      const scoreLabel = company.score == null ? "—" : String(Math.round(company.score));
      const label = `${company.id} · ${scoreLabel}`;
      const isSelected = company.id === selected ? " selected" : "";
      return `<option value="${company.id}"${isSelected}>${label}</option>`;
    })
    .join("");
  companySelect.value = selected;
}

function paint(): void {
  if (!root) return;
  root.innerHTML = renderDashboard(score, executive, tab);
  root.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = button.dataset.tab;
      if (next === "diagnosis" || next === "method") {
        tab = next;
        paint();
      }
    });
  });
  document.querySelector("#open-ai-settings")?.addEventListener("click", openDialog);
  if (companySelect) companySelect.value = score.companyId;
}

function openDialog(): void {
  if (!dialog || !keyInput) return;
  keyInput.value = readSessionApiKey();
  dialogStatus!.textContent = "";
  dialog.showModal();
  keyInput.focus();
}

async function loadCompany(companyId: string, pushUrl = false): Promise<void> {
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

async function load(): Promise<void> {
  paint();
  const companyId = currentCompanyId();
  try {
    const companies = await fetchCompanies();
    fillCompanies(companies, companyId);
  } catch {
    fillCompanies([{ id: companyId, score: null, classification: "NO EVALUABLE" }], companyId);
  }
  await loadCompany(companyId);
}

companySelect?.addEventListener("change", () => {
  const companyId = companySelect.value;
  if (companyId && companyId !== score.companyId) void loadCompany(companyId, true);
});

window.addEventListener("popstate", () => {
  void loadCompany(currentCompanyId());
});

generateButton?.addEventListener("click", async () => {
  const key = keyInput?.value.trim() || "";
  if (key) saveSessionApiKey(key);
  generateButton.disabled = true;
  generateButton.textContent = "Generando…";
  dialogStatus!.textContent = "Gemini está leyendo las señales actuales.";
  try {
    executive = await generateExecutiveSummary(score.companyId, key);
    tab = "diagnosis";
    paint();
    dialog?.close();
  } catch (error) {
    dialogStatus!.textContent =
      error instanceof Error ? error.message : "No se pudo generar el resumen.";
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
