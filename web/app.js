"use strict";

const $ = (sel) => document.querySelector(sel);

const dropzone = $("#dropzone");
const fileInput = $("#fileInput");
const statusEl = $("#status");
const resultsEl = $("#results");

let currentReport = null;
let activeSeverity = "all";

const SEV_LABEL = { critical: "Critique", warning: "Avertissement", info: "Info" };

// ---- Upload wiring --------------------------------------------------------
$("#browseBtn").addEventListener("click", () => fileInput.click());
dropzone.addEventListener("click", (e) => {
  if (e.target.closest("button")) return;       // let the buttons do their own thing
  fileInput.click();
});
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
fileInput.addEventListener("change", () => {
  if (fileInput.files.length) scanFile(fileInput.files[0]);
});

["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); }));
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) scanFile(file);
});

$("#demoBtn").addEventListener("click", scanDemo);

// ---- Network --------------------------------------------------------------
async function scanFile(file) {
  showStatus(`Analyse de « ${file.name} »…`, true);
  const body = new FormData();
  body.append("file", file);
  await runRequest("/api/scan", { method: "POST", body });
}

async function scanDemo() {
  showStatus("Analyse de la base de démonstration…", true);
  await runRequest("/api/demo", { method: "GET" });
}

async function runRequest(url, opts) {
  try {
    const res = await fetch(url, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Erreur ${res.status}`);
    currentReport = data;
    activeSeverity = "all";
    render(data);
  } catch (err) {
    showError(err.message || "Échec de l'analyse.");
  }
}

// ---- Status helpers -------------------------------------------------------
function showStatus(msg, loading) {
  resultsEl.hidden = true;
  statusEl.hidden = false;
  statusEl.className = "status";
  statusEl.innerHTML = (loading ? '<span class="spinner"></span>' : "") + msg;
}
function showError(msg) {
  statusEl.hidden = false;
  statusEl.className = "status error";
  statusEl.textContent = "⚠ " + msg;
}

// ---- Rendering ------------------------------------------------------------
function render(report) {
  statusEl.hidden = true;
  resultsEl.hidden = false;

  const s = report.summary;
  paintScore(s.score);
  $("#dbName").textContent = report.database + (report.demo ? "  (démo)" : "");
  $("#dbMeta").textContent =
    `${s.tables} tables · ${s.rows} lignes · ${s.checks_run} contrôles exécutés · ` +
    `${s.findings} problème(s) détecté(s)`;

  $("#counts").innerHTML = ["critical", "warning", "info"]
    .map((sev) => `<span class="count"><span class="dot ${sev}"></span>${s[sev]} ${SEV_LABEL[sev]}${s[sev] > 1 ? "s" : ""}</span>`)
    .join("");

  // severity filter chips
  document.querySelectorAll("#severityFilters .chip").forEach((chip) => {
    chip.onclick = () => {
      document.querySelectorAll("#severityFilters .chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      activeSeverity = chip.dataset.sev;
      renderFindings();
    };
  });
  $("#search").oninput = renderFindings;

  renderFindings();
  renderTables(report.tables);
  resultsEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

function paintScore(score) {
  const ring = $("#scoreRing");
  const color = score >= 80 ? "var(--good)" : score >= 50 ? "var(--warning)" : "var(--critical)";
  ring.style.setProperty("--c", color);
  ring.style.setProperty("--p", score);
  $("#scoreValue").textContent = score;
  $("#scoreValue").style.color = color;
}

function renderFindings() {
  const term = $("#search").value.trim().toLowerCase();
  const list = currentReport.findings.filter((f) => {
    if (activeSeverity !== "all" && f.severity !== activeSeverity) return false;
    if (!term) return true;
    return (f.table + " " + (f.column || "") + " " + f.title + " " + f.detail)
      .toLowerCase().includes(term);
  });

  const box = $("#findings");
  if (!list.length) {
    box.innerHTML = currentReport.findings.length
      ? '<div class="empty-state">Aucun résultat pour ce filtre.</div>'
      : '<div class="empty-state"><div class="big">✅</div>Aucun bug détecté — base saine !</div>';
    return;
  }

  box.innerHTML = list.map((f) => {
    const loc = f.column ? `${f.table}.${f.column}` : f.table;
    const samples = (f.samples || []).length
      ? `<div class="f-samples">${f.samples.map((x) => `<span class="sample">${esc(String(x))}</span>`).join("")}</div>`
      : "";
    return `
      <div class="finding ${f.severity}">
        <div class="f-head">
          <span class="badge ${f.severity}">${SEV_LABEL[f.severity]}</span>
          <span class="cat">${esc(f.category)}</span>
          <h3 class="f-title">${esc(f.title)}</h3>
          <span class="f-loc">${esc(loc)}</span>
        </div>
        <p class="f-detail">${esc(f.detail)}</p>
        ${samples}
      </div>`;
  }).join("");
}

function renderTables(tables) {
  $("#tableCount").textContent = tables.length;
  $("#tables").innerHTML = tables.map((t) => {
    const fks = t.foreign_keys.length
      ? t.foreign_keys.map((fk) => `${fk.column} → ${fk.references}`).join("<br>")
      : "—";
    return `
      <div class="table-card">
        <h4>${esc(t.name)}</h4>
        <p>${t.rows} lignes · ${t.columns} colonnes</p>
        <p>PK : ${t.primary_key.length ? esc(t.primary_key.join(", ")) : "<em>aucune</em>"}</p>
        <p>FK : ${fks}</p>
      </div>`;
  }).join("");
}

function esc(str) {
  return str.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
