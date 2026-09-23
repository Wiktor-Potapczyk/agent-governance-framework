/**
 * app.js — Observability dashboard frontend
 *
 * Architecture:
 *  - Fetches all events once from /api/events on load and on Refresh.
 *  - Merge-on-refresh: new events are merged by composite key (ts|hook|session|event)
 *    so filter state is preserved across refreshes.
 *  - All DOM injection uses textContent / createElement — never innerHTML with
 *    user-controlled strings. Event field values may contain HTML-like strings
 *    (log reasons echo user prompts); textContent prevents XSS.
 *  - Pagination: 50 rows/page. With 1000 events this is fine.
 *    TODO: if event count exceeds ~10000, consider virtual scrolling instead of
 *    render-all-then-paginate to avoid long paints.
 */

"use strict";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

/**
 * Event types hidden by default (high-volume, low-signal).
 * Users can enable them via the event-type filter checkboxes.
 */
const NOISY_TYPES = new Set([
  "classification_emitted",
  "session_start",
  "session_end",
  "pass",
  "agent_dispatched",
]);

/**
 * Severity category per event type → CSS class + badge class.
 */
const EVENT_CATEGORY = {
  // Failures
  block:                  "failure",
  deny:                   "failure",
  qa_fail_reported:       "failure",
  classifier_field_missing: "failure",
  // Warnings
  warn:                   "warning",
  warning:                "warning",
  "dark-zone":            "warning",
  // Successes
  pass:                   "success",
  allow_process_skill_exemption: "success",
  h11_sidecar_fallback_activated: "success",
  // Informational
  session_start:          "info",
  session_end:            "info",
  agent_dispatched:       "info",
  classification_emitted: "info",
  dashboard_alert:        "info",
  // Telemetry
  token_breakdown:        "telemetry",
  error_summary:          "telemetry",
};

function categoryOf(eventType) {
  return EVENT_CATEGORY[eventType] || "info";
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** Master event array. Append-only; rebuilt only on hard reset. */
let allEvents = [];

/** Set of composite keys for dedup on merge. key = ts|hook|session|event */
const seenKeys = new Set();

/** Currently visible (post-filter) events. */
let filteredEvents = [];

/** Current page index (0-based). */
let currentPage = 0;

/** Which event types are enabled in the filter. Populated on first load. */
const enabledEventTypes = new Set();

/** Set of all observed event types (for building checkboxes). */
const observedEventTypes = new Set();

/** The session selected in the analyze-bar. */
let selectedSession = null;

/** Whether to show error_summary rows inline in Events tab. */
let showAnalysesInline = false;

// Analytics state
const analyticsState = {
  window: "all",
  loaded: false,
  charts: {},          // chartId → Chart instance (for destroy on re-render)
  sessionFilter: null, // cross-tab session filter
};

// Enforcement state
const enforcementState = {
  window: "all",
  loaded: false,
  charts: {},
};

// Session Ledger sort state
const ledgerSort = {
  col: "total_tokens",
  dir: "desc",
};

// Investigation filter state
const invFilters = {
  sessionPrefix: "",
  model: "",
  dateFrom: "",
  dateTo: "",
  sourceTypes: new Set(["block", "deny", "qa_fail_reported", "warn", "warning"]),
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const statsStrip       = document.getElementById("stats-strip");
const sessionFilter    = document.getElementById("session-filter");
const hookFilter       = document.getElementById("hook-filter");
const envFilter        = document.getElementById("env-filter");
const tsFrom           = document.getElementById("ts-from");
const tsTo             = document.getElementById("ts-to");
const btnRefresh       = document.getElementById("btn-refresh");
const etCheckboxes     = document.getElementById("event-type-checkboxes");
const showAnalysesInlineChk = document.getElementById("show-analyses-inline");
const analyzebar       = document.getElementById("analyze-bar");
const analyzeLabel     = document.getElementById("analyze-session-label");
const btnAnalyze       = document.getElementById("btn-analyze");
const analyzeStatus    = document.getElementById("analyze-status");
const btnAnalyzeClose  = document.getElementById("btn-analyze-close");
const tbody            = document.getElementById("events-tbody");
const pagination       = document.getElementById("pagination");
const detailModal      = document.getElementById("detail-modal");
const modalTitle       = document.getElementById("modal-title");
const modalBody        = document.getElementById("modal-body");
const modalClose       = document.getElementById("modal-close");
const modalBackdrop    = detailModal.querySelector(".modal-backdrop");

// ---------------------------------------------------------------------------
// DELTA-4: Tab switcher — initTabs()
// ---------------------------------------------------------------------------

function initTabs() {
  const tabBar = document.getElementById("tab-bar");
  if (!tabBar) return;

  tabBar.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    const targetTab = btn.dataset.tab;
    if (!targetTab) return;

    // Update active button
    tabBar.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");

    // Show/hide panels
    document.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.add("hidden");
    });
    const panel = document.getElementById("tab-" + targetTab);
    if (panel) panel.classList.remove("hidden");

    // Trigger render on first activation
    if (targetTab === "analytics" && !analyticsState.loaded) {
      fetchAndRenderAnalytics();
    }
    if (targetTab === "enforcement" && !enforcementState.loaded) {
      fetchAndRenderEnforcement();
    }
    if (targetTab === "investigation") {
      renderInvestigationCards();
    }
  });
}

// ---------------------------------------------------------------------------
// DELTA-5: /api/query fetch layer
// ---------------------------------------------------------------------------

/**
 * Fetch from /api/query with the given parameters.
 * Returns the parsed JSON body or throws on HTTP error.
 */
async function fetchQuery({ group_by, metric = "count", window = "all", filter_key = "", filter_val = "", top = 15, mode = "" } = {}) {
  const params = new URLSearchParams();
  if (mode)       params.set("mode", mode);
  if (group_by)   params.set("group_by", group_by);
  if (metric)     params.set("metric", metric);
  params.set("window", window);
  if (top)        params.set("top", String(top));
  if (filter_key) params.set("filter_key", filter_key);
  if (filter_val) params.set("filter_val", filter_val);

  const res = await fetch("/api/query?" + params.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

/** Wrapper for the events endpoint (unchanged from Sprint 1). */
async function fetchEvents() {
  const res = await fetch("/api/events");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Fetch + merge events (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

async function fetchAndMerge() {
  btnRefresh.disabled = true;
  btnRefresh.textContent = "Loading…";
  try {
    const data = await fetchEvents();
    mergeEvents(data.events || []);
  } catch (err) {
    console.error("fetchAndMerge error:", err);
  } finally {
    btnRefresh.disabled = false;
    btnRefresh.textContent = "Refresh";
  }
}

function mergeEvents(incoming) {
  for (const ev of incoming) {
    const k = eventKey(ev);
    if (!seenKeys.has(k)) {
      seenKeys.add(k);
      allEvents.push(ev);
      if (ev.event) observedEventTypes.add(ev.event);
    }
  }
  allEvents.sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
  rebuildEventTypeCheckboxes();
  applyFiltersAndRender();
}

// ---------------------------------------------------------------------------
// Composite key for dedup
// ---------------------------------------------------------------------------

function eventKey(ev) {
  return `${ev.ts || ""}|${ev.hook || ""}|${ev.session || ""}|${ev.event || ""}`;
}

// ---------------------------------------------------------------------------
// Event-type checkboxes (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

function rebuildEventTypeCheckboxes() {
  const sorted = Array.from(observedEventTypes).sort();
  const existingTypes = new Set(
    Array.from(etCheckboxes.querySelectorAll("input[data-et]")).map(
      (el) => el.dataset.et
    )
  );
  const needsRebuild = sorted.some((t) => !existingTypes.has(t));
  if (!needsRebuild) return;

  etCheckboxes.innerHTML = "";  // safe: no user content
  for (const et of sorted) {
    // Skip error_summary from the type checkboxes — it lives in Investigation tab
    if (et === "error_summary" && !showAnalysesInline) {
      // Still add to enabledEventTypes only if showAnalysesInline is on
    }
    const cat = categoryOf(et);
    const isNoisy = NOISY_TYPES.has(et);

    if (!enabledEventTypes.has(et) && !isNoisy) {
      enabledEventTypes.add(et);
    }
    const checked = enabledEventTypes.has(et);

    const label = document.createElement("label");
    label.className = "et-checkbox-label";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.et = et;
    cb.checked = checked;
    cb.addEventListener("change", () => {
      if (cb.checked) {
        enabledEventTypes.add(et);
      } else {
        enabledEventTypes.delete(et);
      }
      currentPage = 0;
      applyFiltersAndRender();
    });

    const badge = document.createElement("span");
    badge.className = `ev-badge ${cat}`;
    badge.textContent = et;

    label.appendChild(cb);
    label.appendChild(badge);
    etCheckboxes.appendChild(label);
  }
}

// ---------------------------------------------------------------------------
// Filter application (Sprint 1 — extended with error_summary hide)
// ---------------------------------------------------------------------------

function applyFiltersAndRender() {
  const sessionVal = sessionFilter.value.trim().toLowerCase();
  const hookVal    = hookFilter.value.trim().toLowerCase();
  const envVal     = envFilter.value;
  const fromVal    = tsFrom.value.trim();
  const toVal      = tsTo.value.trim();

  filteredEvents = allEvents.filter((ev) => {
    // Hide error_summary from Events tab unless toggle is on
    if (ev.event === "error_summary" && !showAnalysesInline) return false;

    if (ev.event && !enabledEventTypes.has(ev.event)) return false;
    if (sessionVal && !(ev.session || "").toLowerCase().startsWith(sessionVal)) return false;
    if (hookVal && !(ev.hook || "").toLowerCase().includes(hookVal)) return false;
    if (envVal && ev.environment !== envVal) return false;
    if (fromVal && (ev.ts || "") < fromVal) return false;
    if (toVal   && (ev.ts || "") > toVal + " 99:99:99") return false;

    return true;
  });

  filteredEvents = filteredEvents.slice().reverse();

  updateStatsStrip();
  renderPage();
  renderPagination();
}

// ---------------------------------------------------------------------------
// Stats strip (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

function updateStatsStrip() {
  const todayPrefix = new Date().toISOString().slice(0, 10);
  const total     = allEvents.length;
  const today     = allEvents.filter((ev) => (ev.ts || "").slice(0, 10) === todayPrefix).length;
  const failures  = allEvents.filter((ev) => categoryOf(ev.event) === "failure").length;
  const warnings  = allEvents.filter((ev) => categoryOf(ev.event) === "warning").length;
  const sessions  = new Set(allEvents.map((ev) => ev.session).filter(Boolean)).size;

  statsStrip.innerHTML = "";

  const items = [
    { label: "Total",    value: total,    cls: "" },
    { label: "Today",    value: today,    cls: "" },
    { label: "Failures", value: failures, cls: failures > 0 ? "red" : "" },
    { label: "Warnings", value: warnings, cls: warnings > 0 ? "yellow" : "" },
    { label: "Sessions", value: sessions, cls: "green" },
  ];

  for (const item of items) {
    const div = document.createElement("div");
    div.className = "stat-item";

    const val = document.createElement("span");
    val.className = `stat-value ${item.cls}`.trim();
    val.textContent = item.value;

    const lbl = document.createElement("span");
    lbl.className = "stat-label";
    lbl.textContent = item.label;

    div.appendChild(val);
    div.appendChild(lbl);
    statsStrip.appendChild(div);
  }
}

// ---------------------------------------------------------------------------
// Table rendering (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

function renderPage() {
  tbody.innerHTML = "";

  const start = currentPage * PAGE_SIZE;
  const slice = filteredEvents.slice(start, start + PAGE_SIZE);

  if (slice.length === 0) {
    const tr = document.createElement("tr");
    tr.className = "empty-row";
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = "No events match the current filters.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const ev of slice) {
    const cat = categoryOf(ev.event);
    const tr = document.createElement("tr");
    tr.className = `ev-${cat}`;

    tr.appendChild(makeCell(ev.ts || "", "col-ts"));

    const evCell = document.createElement("td");
    evCell.className = "col-event";
    const badge = document.createElement("span");
    badge.className = `ev-badge ${cat}`;
    badge.textContent = ev.event || "";
    evCell.appendChild(badge);
    tr.appendChild(evCell);

    tr.appendChild(makeCell(ev.hook || "", "col-hook"));

    const sess = ev.session || "";
    tr.appendChild(makeCell(sess.slice(0, 12) + (sess.length > 12 ? "\u2026" : ""), "col-session"));

    tr.appendChild(makeCell(ev.environment || "", "col-env"));

    const detailCell = document.createElement("td");
    detailCell.className = "col-detail";
    detailCell.appendChild(buildDetailSpan(ev));
    tr.appendChild(detailCell);

    tr.addEventListener("click", () => {
      openModal(ev);
    });

    tbody.appendChild(tr);
  }
}

function buildDetailSpan(ev) {
  const span = document.createElement("span");
  span.className = "detail-muted";

  let detail = "";

  switch (ev.event) {
    case "block": {
      const hf = Array.isArray(ev.hard_failures) ? ev.hard_failures[0] : ev.reason || "";
      const missing = Array.isArray(ev.missing) ? ev.missing.join(", ") : ev.missing || "";
      detail = hf || (missing ? `missing: ${missing}` : "");
      if (ev.hook === "dispatch-compliance" && missing) detail = `missing dispatches: ${missing}`;
      break;
    }
    case "deny":
      detail = ev.reason || ev.must_dispatch || "";
      break;
    case "qa_fail_reported": {
      const fails = Array.isArray(ev.fails) ? ev.fails.slice(0, 2).join("; ") : "";
      detail = `${ev.fail_count || 0} fail(s)${fails ? ": " + fails : ""}`;
      break;
    }
    case "classifier_field_missing":
      detail = `missing: ${Array.isArray(ev.missing) ? ev.missing.join(", ") : ev.missing || ""}`;
      break;
    case "warn":
      detail = ev.check || "";
      break;
    case "warning":
      detail = ev.warning || ev.task_type || "";
      break;
    case "dark-zone":
      detail = `${ev.agent_count || 0} agent(s) \xb7 citations: ${ev.citation_count || 0} \xb7 severity: ${ev.severity || ""}`;
      break;
    case "pass":
      detail = `matched ${ev.matched_count || 0}/${ev.declared_count || 0}`;
      break;
    case "agent_dispatched":
      detail = `${ev.agent_type || ""} \u2192 ${ev.outcome || ""}${ev.warn_downgrade ? " [warn-downgrade]" : ""}`;
      break;
    case "classification_emitted":
      detail = `${ev.type || ""} \xb7 complete:${ev.complete}`;
      if (ev.implies) detail += ` \xb7 ${String(ev.implies).slice(0, 80)}`;
      break;
    case "session_start":
      detail = ev.source || "";
      break;
    case "session_end":
      detail = `turns:${ev.turn_count || 0} \xb7 tokens:${(ev.approx_tokens || 0).toLocaleString()} \xb7 dur:${ev.duration_sec || 0}s`;
      break;
    case "token_breakdown": {
      const ms = ev.main_session || {};
      const total = ev.turn_total_tokens || 0;
      detail = `total:${total.toLocaleString()} \xb7 in:${(ms.input_tokens || 0).toLocaleString()} out:${(ms.output_tokens || 0).toLocaleString()} cache_read:${(ms.cache_read_input_tokens || 0).toLocaleString()}`;
      break;
    }
    case "error_summary":
      detail = ev.summary || "";
      break;
    case "dashboard_alert":
      detail = Array.isArray(ev.alerts) ? ev.alerts.join("; ") : "";
      break;
    case "allow_process_skill_exemption":
      detail = `agent:${ev.agent_type || ""} must_dispatch:${ev.must_dispatch || ""}`;
      break;
    case "h11_sidecar_fallback_activated":
      detail = `skill:${ev.skill || ""} must_dispatch:${ev.must_dispatch || ""}`;
      break;
    default:
      detail = _genericDetail(ev);
  }

  span.textContent = detail;
  return span;
}

function _genericDetail(ev) {
  const skip = new Set(["ts", "event", "hook", "session", "schema", "environment"]);
  for (const [k, v] of Object.entries(ev)) {
    if (skip.has(k)) continue;
    if (v === null || v === undefined || v === "") continue;
    if (typeof v === "object") return `${k}: ${JSON.stringify(v).slice(0, 100)}`;
    return `${k}: ${String(v).slice(0, 120)}`;
  }
  return "";
}

function makeCell(text, cls) {
  const td = document.createElement("td");
  td.className = cls;
  td.textContent = text;
  return td;
}

// ---------------------------------------------------------------------------
// Pagination (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

function renderPagination() {
  pagination.innerHTML = "";

  const totalPages = Math.max(1, Math.ceil(filteredEvents.length / PAGE_SIZE));

  if (totalPages <= 1) {
    const info = document.createElement("span");
    info.className = "page-info";
    info.textContent = `${filteredEvents.length} event(s)`;
    pagination.appendChild(info);
    return;
  }

  const prev = makePageBtn("\u2190 Prev", currentPage === 0, () => {
    currentPage--;
    renderPage();
    renderPagination();
    window.scrollTo(0, 0);
  });
  pagination.appendChild(prev);

  const pageNums = buildPageRange(currentPage, totalPages);
  for (const p of pageNums) {
    if (p === "\u2026") {
      const ellipsis = document.createElement("span");
      ellipsis.className = "page-info";
      ellipsis.textContent = "\u2026";
      pagination.appendChild(ellipsis);
    } else {
      const btn = makePageBtn(String(p + 1), false, () => {
        currentPage = p;
        renderPage();
        renderPagination();
        window.scrollTo(0, 0);
      });
      if (p === currentPage) btn.classList.add("active");
      pagination.appendChild(btn);
    }
  }

  const next = makePageBtn("Next \u2192", currentPage >= totalPages - 1, () => {
    currentPage++;
    renderPage();
    renderPagination();
    window.scrollTo(0, 0);
  });
  pagination.appendChild(next);

  const info = document.createElement("span");
  info.className = "page-info";
  const start = currentPage * PAGE_SIZE + 1;
  const end = Math.min((currentPage + 1) * PAGE_SIZE, filteredEvents.length);
  info.textContent = `${start}\u2013${end} of ${filteredEvents.length}`;
  pagination.appendChild(info);
}

function buildPageRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i);
  const result = [];
  if (current <= 3) {
    for (let i = 0; i < 5; i++) result.push(i);
    result.push("\u2026");
    result.push(total - 1);
  } else if (current >= total - 4) {
    result.push(0);
    result.push("\u2026");
    for (let i = total - 5; i < total; i++) result.push(i);
  } else {
    result.push(0);
    result.push("\u2026");
    for (let i = current - 1; i <= current + 1; i++) result.push(i);
    result.push("\u2026");
    result.push(total - 1);
  }
  return result;
}

function makePageBtn(label, disabled, onClick) {
  const btn = document.createElement("button");
  btn.className = "page-btn";
  btn.textContent = label;
  btn.disabled = disabled;
  if (!disabled) btn.addEventListener("click", onClick);
  return btn;
}

// ---------------------------------------------------------------------------
// Modal (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

function openModal(ev) {
  modalBody.textContent = JSON.stringify(ev, null, 2);
  const titleParts = [ev.event, ev.hook].filter(Boolean);
  modalTitle.textContent = titleParts.join(" \xb7 ");
  detailModal.classList.remove("hidden");

  if (ev.session) {
    selectedSession = ev.session;
    analyzeLabel.textContent = `Session: ${ev.session}`;
    analyzeStatus.textContent = "";
    analyzebar.classList.remove("hidden");
  }
}

function closeModal() {
  detailModal.classList.add("hidden");
}

modalClose.addEventListener("click", closeModal);
modalBackdrop.addEventListener("click", closeModal);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

// ---------------------------------------------------------------------------
// Analyze-bar (Sprint 1 — preserved)
// ---------------------------------------------------------------------------

btnAnalyzeClose.addEventListener("click", () => {
  analyzebar.classList.add("hidden");
  selectedSession = null;
  analyzeStatus.textContent = "";
});

btnAnalyze.addEventListener("click", async () => {
  if (!selectedSession) return;

  const MAX_N = 5;
  const costEstimate = (0.0005 * MAX_N).toFixed(4);
  const etaSeconds = 30 * MAX_N;

  btnAnalyze.disabled = true;
  analyzeStatus.textContent = `Running Haiku summarizer (\u2264${MAX_N} events, ~${etaSeconds}s, ~$${costEstimate})\u2026`;

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session: selectedSession, max: MAX_N }),
    });
    const data = await res.json();

    if (data.error) {
      const detail = data.detail || "";
      const summaries = (typeof data.summaries_created === "number") ? ` (${data.summaries_created} summaries created before timeout)` : "";
      analyzeStatus.textContent = `Error: ${data.error} \u2014 ${detail}${summaries}`;
      if (typeof data.summaries_created === "number" && data.summaries_created > 0) {
        await fetchAndMerge();
      }
    } else if (data.ok) {
      const n = data.summaries_created ?? 0;
      analyzeStatus.textContent = `Done. ${n} summar${n === 1 ? "y" : "ies"} created.`;
      await fetchAndMerge();
    } else {
      const n = data.summaries_created ?? 0;
      const stderrHint = (data.stderr || "").trim().slice(0, 160);
      analyzeStatus.textContent = `No summaries created (${n}). ${stderrHint ? "Worker stderr: " + stderrHint : "Check haiku-summarize.log for details."}`;
    }
  } catch (err) {
    analyzeStatus.textContent = `Fetch failed: ${err.message}`;
  } finally {
    btnAnalyze.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// Toolbar event handlers (Sprint 1 — preserved + extended)
// ---------------------------------------------------------------------------

btnRefresh.addEventListener("click", fetchAndMerge);

[sessionFilter, hookFilter, tsFrom, tsTo].forEach((el) =>
  el.addEventListener("input", () => {
    currentPage = 0;
    applyFiltersAndRender();
  })
);

envFilter.addEventListener("change", () => {
  currentPage = 0;
  applyFiltersAndRender();
});

// Show-analyses-inline toggle (§2.6)
showAnalysesInlineChk.addEventListener("change", () => {
  showAnalysesInline = showAnalysesInlineChk.checked;
  if (showAnalysesInline) {
    enabledEventTypes.add("error_summary");
  } else {
    enabledEventTypes.delete("error_summary");
  }
  currentPage = 0;
  applyFiltersAndRender();
});

// ---------------------------------------------------------------------------
// DELTA-6 & DELTA-7 & DELTA-8: Analytics tab
// ---------------------------------------------------------------------------

/**
 * Destroy a Chart.js instance safely.
 * @param {string} id - key in analyticsState.charts
 */
function destroyChart(stateObj, id) {
  if (stateObj.charts[id]) {
    stateObj.charts[id].destroy();
    delete stateObj.charts[id];
  }
}

/**
 * Build a Chart.js horizontal bar chart.
 * @param {HTMLCanvasElement} canvas
 * @param {string[]} labels
 * @param {number[]} values
 * @param {string} label
 * @param {string} color
 * @returns {Chart}
 */
function buildHorizontalBar(canvas, labels, values, label, color) {
  return new window.Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{ label, data: values, backgroundColor: color, borderWidth: 0 }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { mode: "index" },
      },
      scales: {
        x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } },
        y: { ticks: { color: "#c9d1d9", font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
}

/**
 * Build a Chart.js vertical bar chart.
 */
function buildVerticalBar(canvas, labels, values, label, color) {
  return new window.Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [{ label, data: values, backgroundColor: color, borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { mode: "index" },
      },
      scales: {
        x: { ticks: { color: "#8b949e", font: { size: 10 } }, grid: { color: "#21262d" } },
        y: { ticks: { color: "#c9d1d9" }, grid: { color: "#21262d" } },
      },
    },
  });
}

/** Render KPI cards into #kpi-cards. */
function renderKpiCards(kpis) {
  const container = document.getElementById("kpi-cards");
  container.innerHTML = "";  // safe: only numbers + literals

  const cards = [
    {
      label: "Total Tokens",
      value: (kpis.total_tokens || 0).toLocaleString(),
      sub: "window sum",
      cls: "",
    },
    {
      label: "Distinct Sessions",
      value: (kpis.distinct_sessions || 0).toLocaleString(),
      sub: "schema-v2 events",
      cls: "green",
    },
    {
      label: "Enforcement Trigger Rate",
      value: `${kpis.enforcement_trigger_rate ?? 0}%`,
      sub: `${kpis.enforcement_numerator ?? 0} / ${kpis.enforcement_denominator ?? 0} hook events \u2191 = more enforcement fired`,
      cls: (kpis.enforcement_trigger_rate || 0) > 10 ? "yellow" : "",
    },
    {
      label: "Ungoverned Dispatch Rate",
      value: `${kpis.ungoverned_dispatch_rate ?? 0}%`,
      sub: `${kpis.ungoverned_numerator ?? 0} no_classification / ${kpis.ungoverned_denominator ?? 0} dispatches`,
      cls: (kpis.ungoverned_dispatch_rate || 0) > 20 ? "red" : "",
    },
  ];

  for (const card of cards) {
    const div = document.createElement("div");
    div.className = "kpi-card";

    const valEl = document.createElement("div");
    valEl.className = `kpi-value ${card.cls}`.trim();
    valEl.textContent = card.value;

    const labelEl = document.createElement("div");
    labelEl.className = "kpi-label";
    labelEl.textContent = card.label;

    const subEl = document.createElement("div");
    subEl.className = "kpi-sub";
    subEl.textContent = card.sub;

    div.appendChild(valEl);
    div.appendChild(labelEl);
    div.appendChild(subEl);
    container.appendChild(div);
  }
}

/** Fetch all analytics data and render all panels. */
async function fetchAndRenderAnalytics() {
  analyticsState.loaded = true;
  const win = analyticsState.window;
  const top = 15;
  // D1: build session filter params once; applied to all panels except the
  // Session Ledger itself (filtering the ledger to a single session is degenerate).
  const sf = analyticsState.sessionFilter;
  const sfParams = sf ? { filter_key: "session_id", filter_val: sf } : {};

  try {
    // Parallel fetches
    const [
      kpisData,
      toolCallsData,
      hookRunsData,
      hookBlocksData,
      agentDispatchData,
      agentOutcomeData,
      agentTokenData,
      ledgerData,
      govHealthData,
    ] = await Promise.all([
      fetchQuery({ mode: "kpis", window: win, ...sfParams }),
      fetchQuery({ group_by: "tool_type", metric: "count", window: win, top, ...sfParams }),
      fetchQuery({ group_by: "hook", metric: "run_count", window: win, top, ...sfParams }),
      fetchQuery({ group_by: "hook", metric: "block_count", window: win, top, ...sfParams }),
      fetchQuery({ group_by: "agent_type", metric: "count", window: win, top, ...sfParams }),
      fetchQuery({ group_by: "outcome", metric: "count", window: win, top, ...sfParams }),
      fetchQuery({ group_by: "agent_type", metric: "turn_total_tokens", window: win, top, ...sfParams }),
      fetchQuery({ mode: "session_ledger", window: win }), // ledger not filtered — cross-session overview
      fetchQuery({ mode: "governance_health", window: win, ...sfParams }),
    ]);

    // KPI cards
    renderKpiCards(kpisData);

    // Tool calls
    destroyChart(analyticsState, "toolCalls");
    const tcCanvas = document.getElementById("chart-tool-calls");
    if (tcCanvas && toolCallsData.data && toolCallsData.data.length > 0) {
      analyticsState.charts.toolCalls = buildHorizontalBar(
        tcCanvas,
        toolCallsData.data.map((d) => d.key),
        toolCallsData.data.map((d) => d.value),
        "Tool Call Count",
        "rgba(88, 166, 255, 0.7)"
      );
    }

    // Hook runs
    destroyChart(analyticsState, "hookRuns");
    const hrCanvas = document.getElementById("chart-hook-runs");
    if (hrCanvas && hookRunsData.data && hookRunsData.data.length > 0) {
      analyticsState.charts.hookRuns = buildHorizontalBar(
        hrCanvas,
        hookRunsData.data.map((d) => d.key),
        hookRunsData.data.map((d) => d.value),
        "Run Count",
        "rgba(63, 185, 80, 0.7)"
      );
    }

    // Hook blocks
    destroyChart(analyticsState, "hookBlocks");
    const hbCanvas = document.getElementById("chart-hook-blocks");
    if (hbCanvas && hookBlocksData.data && hookBlocksData.data.length > 0) {
      analyticsState.charts.hookBlocks = buildHorizontalBar(
        hbCanvas,
        hookBlocksData.data.map((d) => d.key),
        hookBlocksData.data.map((d) => d.value),
        "Block+Deny Count",
        "rgba(248, 81, 73, 0.7)"
      );
    }

    // Agent dispatches
    destroyChart(analyticsState, "agentDispatches");
    const adCanvas = document.getElementById("chart-agent-dispatches");
    if (adCanvas && agentDispatchData.data && agentDispatchData.data.length > 0) {
      analyticsState.charts.agentDispatches = buildHorizontalBar(
        adCanvas,
        agentDispatchData.data.map((d) => d.key),
        agentDispatchData.data.map((d) => d.value),
        "Dispatch Count",
        "rgba(210, 153, 34, 0.7)"
      );
    }

    // Agent outcome distribution
    destroyChart(analyticsState, "agentOutcomes");
    const aoCanvas = document.getElementById("chart-agent-outcomes");
    if (aoCanvas && agentOutcomeData.data && agentOutcomeData.data.length > 0) {
      const outcomeColors = {
        allow: "rgba(63, 185, 80, 0.7)",
        always_allowed: "rgba(63, 185, 80, 0.4)",
        allow_exemption: "rgba(88, 166, 255, 0.6)",
        no_classification: "rgba(248, 81, 73, 0.7)",
      };
      analyticsState.charts.agentOutcomes = buildVerticalBar(
        aoCanvas,
        agentOutcomeData.data.map((d) => d.key),
        agentOutcomeData.data.map((d) => d.value),
        "Count",
        agentOutcomeData.data.map((d) => outcomeColors[d.key] || "rgba(139, 148, 158, 0.5)")
      );
    }

    // Agent token burn (approximate)
    destroyChart(analyticsState, "agentTokens");
    const atCanvas = document.getElementById("chart-agent-tokens");
    if (atCanvas && agentTokenData.data && agentTokenData.data.length > 0) {
      analyticsState.charts.agentTokens = buildHorizontalBar(
        atCanvas,
        agentTokenData.data.map((d) => d.key),
        agentTokenData.data.map((d) => d.value),
        "Total Tokens (approx)",
        "rgba(88, 166, 255, 0.4)"
      );
    }

    // Session Ledger (DELTA-8)
    renderSessionLedger(ledgerData.rows || []);

    // Governance Health
    destroyChart(analyticsState, "darkezoneHist");
    destroyChart(analyticsState, "severity");
    const ghData = govHealthData;
    const dzCanvas = document.getElementById("chart-darkzone-hist");
    if (dzCanvas && ghData.histogram && ghData.histogram.labels.length > 0) {
      analyticsState.charts.darkezoneHist = buildVerticalBar(
        dzCanvas,
        ghData.histogram.labels,
        ghData.histogram.counts,
        "Event Count",
        "rgba(210, 153, 34, 0.7)"
      );
    }

    const sevCanvas = document.getElementById("chart-severity");
    if (sevCanvas && ghData.severity_counts) {
      const sevLabels = Object.keys(ghData.severity_counts);
      const sevVals = Object.values(ghData.severity_counts);
      const sevColors = { low: "rgba(63, 185, 80, 0.7)", medium: "rgba(210, 153, 34, 0.7)", high: "rgba(248, 81, 73, 0.7)" };
      analyticsState.charts.severity = buildVerticalBar(
        sevCanvas,
        sevLabels,
        sevVals,
        "Count",
        sevLabels.map((l) => sevColors[l] || "rgba(139, 148, 158, 0.5)")
      );
    }

  } catch (err) {
    console.error("fetchAndRenderAnalytics error:", err);
  }
}

// ---------------------------------------------------------------------------
// DELTA-8: Session Ledger
// ---------------------------------------------------------------------------

/** Render the Session Ledger table. */
function renderSessionLedger(rows) {
  const tbody = document.getElementById("session-ledger-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";  // safe: rebuilt from server data

  // Apply sort
  const col = ledgerSort.col;
  const dir = ledgerSort.dir === "asc" ? 1 : -1;

  const sorted = rows.slice().sort((a, b) => {
    const va = a[col] ?? -Infinity;
    const vb = b[col] ?? -Infinity;
    if (typeof va === "string") return dir * va.localeCompare(vb);
    return dir * (va - vb);
  });

  for (const row of sorted) {
    const tr = document.createElement("tr");
    tr.className = "ledger-row";

    // Session (truncated)
    const sessVal = row.session || "";
    const sessTd = document.createElement("td");
    sessTd.textContent = sessVal.slice(0, 16) + (sessVal.length > 16 ? "\u2026" : "");
    sessTd.title = sessVal;
    tr.appendChild(sessTd);

    tr.appendChild(makeLedgerCell(row.duration_sec != null ? row.duration_sec.toLocaleString() : "\u2014"));
    tr.appendChild(makeLedgerCell(row.turn_count != null ? row.turn_count : "\u2014"));
    tr.appendChild(makeLedgerCell(row.total_tokens != null ? row.total_tokens.toLocaleString() : "\u2014"));
    tr.appendChild(makeLedgerCell(row.block_count != null ? row.block_count : "\u2014"));
    tr.appendChild(makeLedgerCell(row.dark_zone_count != null ? row.dark_zone_count : "\u2014"));
    tr.appendChild(makeLedgerCell(row.classification_complete_pct != null ? `${row.classification_complete_pct}%` : "\u2014"));

    // Click → cross-tab session filter
    tr.addEventListener("click", () => {
      setSessionFilter(row.session);
    });

    tbody.appendChild(tr);
  }

  // Wire sortable column headers
  const table = document.getElementById("session-ledger-table");
  if (table) {
    table.querySelectorAll("th[data-sort-col]").forEach((th) => {
      // Remove old listeners by cloning
      const newTh = th.cloneNode(true);
      th.parentNode.replaceChild(newTh, th);
      newTh.style.cursor = "pointer";
      if (newTh.dataset.sortCol === ledgerSort.col) {
        newTh.textContent += ledgerSort.dir === "asc" ? " \u25b2" : " \u25bc";
      }
      newTh.addEventListener("click", () => {
        const c = newTh.dataset.sortCol;
        if (ledgerSort.col === c) {
          ledgerSort.dir = ledgerSort.dir === "asc" ? "desc" : "asc";
        } else {
          ledgerSort.col = c;
          ledgerSort.dir = "desc";
        }
        renderSessionLedger(rows);
      });
    });
  }
}

function makeLedgerCell(val) {
  const td = document.createElement("td");
  td.textContent = String(val);
  return td;
}

/** Set cross-tab session filter. */
function setSessionFilter(sessionId) {
  analyticsState.sessionFilter = sessionId;

  const badge = document.getElementById("session-filter-badge");
  const label = document.getElementById("active-session-filter-label");
  if (badge && label) {
    label.textContent = sessionId ? sessionId.slice(0, 16) + "\u2026" : "";
    if (sessionId) {
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  }

  // Re-fetch with filter applied (simplest: reload analytics)
  analyticsState.loaded = false;
  fetchAndRenderAnalytics();
}

// Clear session filter button
document.addEventListener("DOMContentLoaded", () => {
  const clearBtn = document.getElementById("btn-clear-session-filter");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      setSessionFilter(null);
    });
  }

  // Analytics time window buttons
  const analyticsWindowBtns = document.getElementById("analytics-window-btns");
  if (analyticsWindowBtns) {
    analyticsWindowBtns.addEventListener("click", (e) => {
      const btn = e.target.closest(".window-btn");
      if (!btn) return;
      analyticsWindowBtns.querySelectorAll(".window-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      analyticsState.window = btn.dataset.window;
      analyticsState.loaded = false;
      // Destroy all charts so they re-render cleanly
      Object.keys(analyticsState.charts).forEach((k) => destroyChart(analyticsState, k));
      fetchAndRenderAnalytics();
    });
  }

  // Enforcement time window buttons
  const enfWindowBtns = document.getElementById("enforcement-window-btns");
  if (enfWindowBtns) {
    enfWindowBtns.addEventListener("click", (e) => {
      const btn = e.target.closest(".window-btn");
      if (!btn) return;
      enfWindowBtns.querySelectorAll(".window-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      enforcementState.window = btn.dataset.window;
      enforcementState.loaded = false;
      Object.keys(enforcementState.charts).forEach((k) => destroyChart(enforcementState, k));
      fetchAndRenderEnforcement();
    });
  }
});

// ---------------------------------------------------------------------------
// Investigation tab (T1-T6)
// ---------------------------------------------------------------------------

/** Populate source-type checkboxes for Investigation filter. */
function buildInvSourceTypeCheckboxes() {
  const container = document.getElementById("inv-source-type-checkboxes");
  if (!container) return;
  if (container.querySelector("input")) return;  // already built

  const types = ["block", "deny", "qa_fail_reported", "warn", "warning"];
  for (const t of types) {
    const label = document.createElement("label");
    label.className = "et-checkbox-label";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.invType = t;
    cb.checked = invFilters.sourceTypes.has(t);
    cb.addEventListener("change", () => {
      if (cb.checked) invFilters.sourceTypes.add(t);
      else invFilters.sourceTypes.delete(t);
      renderInvestigationCards();
    });

    const badge = document.createElement("span");
    badge.className = `ev-badge ${categoryOf(t)}`;
    badge.textContent = t;

    label.appendChild(cb);
    label.appendChild(badge);
    container.appendChild(label);
  }
}

/** Render investigation cards from allEvents filtered to error_summary. */
function renderInvestigationCards() {
  buildInvSourceTypeCheckboxes();

  const container = document.getElementById("investigation-cards");
  if (!container) return;
  container.innerHTML = "";  // safe: rebuilt from data

  const invSessionVal = (document.getElementById("inv-session-filter") || {}).value || "";
  const invModelVal   = (document.getElementById("inv-model-filter") || {}).value || "";
  const invDateFrom   = (document.getElementById("inv-date-from") || {}).value || "";
  const invDateTo     = (document.getElementById("inv-date-to") || {}).value || "";

  const invEvents = allEvents.filter((ev) => {
    if (ev.event !== "error_summary") return false;
    if (invSessionVal && !(ev.session || "").toLowerCase().startsWith(invSessionVal.toLowerCase())) return false;
    if (invModelVal && !(ev.model || "").toLowerCase().includes(invModelVal.toLowerCase())) return false;
    if (invDateFrom && (ev.ts || "") < invDateFrom) return false;
    if (invDateTo   && (ev.ts || "") > invDateTo + " 99:99:99") return false;
    if (invFilters.sourceTypes.size > 0) {
      const st = ev.source_event_type || "";
      // Coalesce warn/warning
      const normalised = st === "warning" ? "warn" : st;
      if (!invFilters.sourceTypes.has(normalised) && !invFilters.sourceTypes.has(st)) return false;
    }
    return true;
  });

  // Sort newest-first
  const sorted = invEvents.slice().sort((a, b) => (b.ts || "").localeCompare(a.ts || ""));

  if (sorted.length === 0) {
    const empty = document.createElement("div");
    empty.className = "investigation-empty";
    empty.textContent = "No analyses yet. Click \u2018Analyze \u2736\u2019 on any Events row to generate a Haiku summary.";
    container.appendChild(empty);
    return;
  }

  for (const ev of sorted) {
    container.appendChild(buildInvestigationCard(ev));
  }
}

/** Build a single investigation card element. */
function buildInvestigationCard(ev) {
  const card = document.createElement("div");
  card.className = "investigation-card";
  card.dataset.eventId = ev.ts + "|" + (ev.session || "");

  // Headline
  const headline = document.createElement("div");
  headline.className = "card-headline";
  headline.textContent = ev.summary || "(no summary)";
  card.appendChild(headline);

  // Metadata row
  const meta = document.createElement("div");
  meta.className = "card-meta";

  const metaFields = [
    ["session", (ev.session || "").slice(0, 16)],
    ["hook", ev.hook || ""],
    ["model", ev.model || ""],
    ["source_event", ev.source_event_type || ""],
    ["ts", (ev.ts || "").slice(0, 10)],
  ];
  for (const [k, v] of metaFields) {
    if (!v) continue;
    const span = document.createElement("span");
    span.className = "meta-field";
    const keyEl = document.createElement("span");
    keyEl.className = "meta-key";
    keyEl.textContent = k + ": ";
    const valEl = document.createElement("span");
    valEl.textContent = v;
    span.appendChild(keyEl);
    span.appendChild(valEl);
    meta.appendChild(span);
  }
  card.appendChild(meta);

  // Drill-down toggle
  const drillToggle = document.createElement("button");
  drillToggle.className = "btn-ghost drill-toggle";
  drillToggle.textContent = "\u25bc Show source event";
  card.appendChild(drillToggle);

  // Drill-down body (hidden initially)
  const drillBody = document.createElement("div");
  drillBody.className = "card-detail hidden";
  card.appendChild(drillBody);

  drillToggle.addEventListener("click", () => {
    const isOpen = !drillBody.classList.contains("hidden");
    if (isOpen) {
      drillBody.classList.add("hidden");
      drillToggle.textContent = "\u25bc Show source event";
    } else {
      // Lookup source event by source_event_id
      const srcId = ev.source_event_id;
      drillBody.innerHTML = "";  // safe: rebuilt
      if (srcId) {
        const sourceEv = allEvents.find((e) => e.id === srcId || e.ts === srcId);
        const pre = document.createElement("pre");
        pre.className = "drill-json";
        if (sourceEv) {
          pre.textContent = JSON.stringify(sourceEv, null, 2);
        } else {
          pre.textContent = "Source event not found in current data window.";
        }
        drillBody.appendChild(pre);
      } else {
        const msg = document.createElement("p");
        msg.textContent = "Source event not found in current data window.";
        drillBody.appendChild(msg);
      }
      drillBody.classList.remove("hidden");
      drillToggle.textContent = "\u25b2 Hide source event";
    }
  });

  // Re-ask stub button
  const reaskBtn = document.createElement("button");
  reaskBtn.className = "btn-ghost reask-btn";
  reaskBtn.disabled = true;
  reaskBtn.textContent = "Re-ask with context \u21bb";
  reaskBtn.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/reask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ event_id: ev.ts }) });
      const data = await res.json();
      // Show toast
      showToast(data.detail || "Not available yet.");
    } catch {
      showToast("Not available yet.");
    }
  });
  card.appendChild(reaskBtn);

  return card;
}

/** Show a brief toast notification. */
function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  // Fade out after 3s
  setTimeout(() => {
    toast.classList.add("toast-fade");
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 400);
  }, 3000);
}

// Wire investigation filter inputs
document.addEventListener("DOMContentLoaded", () => {
  ["inv-session-filter", "inv-model-filter", "inv-date-from", "inv-date-to"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("input", renderInvestigationCards);
  });
});

// ---------------------------------------------------------------------------
// DELTA-9: Enforcement tab
// ---------------------------------------------------------------------------

async function fetchAndRenderEnforcement() {
  enforcementState.loaded = true;
  const win = enforcementState.window;

  try {
    const [hookBlocksData, kpisData] = await Promise.all([
      fetchQuery({ group_by: "hook", metric: "block_count", window: win, top: 20 }),
      fetchQuery({ mode: "kpis", window: win }),
    ]);

    // Enforcement Trigger Rate chart — single-value gauge rendered as a simple bar
    destroyChart(enforcementState, "enfRate");
    const erfCanvas = document.getElementById("chart-enforcement-rate");
    if (erfCanvas) {
      const etr = kpisData.enforcement_trigger_rate ?? 0;
      enforcementState.charts.enfRate = new window.Chart(erfCanvas, {
        type: "bar",
        data: {
          labels: ["Enforcement Trigger Rate"],
          datasets: [
            {
              label: "Enforcement Trigger Rate %",
              data: [etr],
              backgroundColor: etr > 15 ? "rgba(248, 81, 73, 0.7)" : etr > 5 ? "rgba(210, 153, 34, 0.7)" : "rgba(63, 185, 80, 0.7)",
              borderWidth: 0,
            },
            {
              label: "Remaining",
              data: [Math.max(0, 100 - etr)],
              backgroundColor: "rgba(48, 54, 61, 0.5)",
              borderWidth: 0,
            },
          ],
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => ctx.datasetIndex === 0 ? `${etr}% (${kpisData.enforcement_numerator} / ${kpisData.enforcement_denominator} hook events)` : "",
              },
            },
          },
          scales: {
            x: { max: 100, ticks: { color: "#8b949e", callback: (v) => v + "%" }, grid: { color: "#21262d" } },
            y: { ticks: { color: "#c9d1d9" }, grid: { display: false } },
          },
        },
      });
    }

    // Top blocked hooks table
    renderTopBlockedHooks(hookBlocksData.data || []);

    // Wired combination matrix (DELTA-10)
    renderCombinationMatrix();

  } catch (err) {
    console.error("fetchAndRenderEnforcement error:", err);
  }
}

/** Render top blocked hooks table. */
function renderTopBlockedHooks(data) {
  const tbody = document.getElementById("top-blocked-hooks-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (data.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 2;
    td.textContent = "No block/deny events in this window.";
    td.className = "empty-cell";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const row of data) {
    const tr = document.createElement("tr");
    const hookTd = document.createElement("td");
    hookTd.textContent = row.key;
    const countTd = document.createElement("td");
    countTd.textContent = row.value;
    tr.appendChild(hookTd);
    tr.appendChild(countTd);
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// DELTA-10: Wired-combination matrix UI
// ---------------------------------------------------------------------------

const MATRIX_GROUP_BY = ["hook", "event", "agent_type", "session", "severity", "outcome", "tool_type"];
const MATRIX_METRICS  = ["count", "turn_total_tokens", "block_count", "ratio_avg", "ratio_max", "run_count"];
const MATRIX_WIRED = {
  "hook+count": true,
  "hook+block_count": true,
  "hook+run_count": true,
  "event+count": true,
  "agent_type+count": true,
  "agent_type+run_count": true,
  "agent_type+turn_total_tokens": "approximate",
  "session+count": true,
  "session+turn_total_tokens": true,
  "session+block_count": true,
  "session+ratio_avg": true,
  "session+ratio_max": true,
  "severity+count": true,
  "outcome+count": true,
  "tool_type+count": true,
};

function renderCombinationMatrix() {
  const container = document.getElementById("combination-matrix-container");
  if (!container) return;
  container.innerHTML = "";  // safe: rebuilt from constants

  const table = document.createElement("table");
  table.className = "combination-matrix";

  // Header row
  const thead = document.createElement("thead");
  const hRow = document.createElement("tr");
  const cornerTh = document.createElement("th");
  cornerTh.textContent = "group_by \\ metric";
  hRow.appendChild(cornerTh);
  for (const m of MATRIX_METRICS) {
    const th = document.createElement("th");
    th.textContent = m;
    hRow.appendChild(th);
  }
  thead.appendChild(hRow);
  table.appendChild(thead);

  // Body rows
  const tbody = document.createElement("tbody");
  for (const g of MATRIX_GROUP_BY) {
    const tr = document.createElement("tr");
    const rowLabel = document.createElement("th");
    rowLabel.textContent = g;
    tr.appendChild(rowLabel);

    for (const m of MATRIX_METRICS) {
      const key = `${g}+${m}`;
      const support = MATRIX_WIRED[key];
      const td = document.createElement("td");
      if (support === true) {
        td.textContent = "\u2713";
        td.className = "matrix-supported";
      } else if (support === "approximate") {
        td.textContent = "\u26A0";
        td.className = "matrix-approx";
        td.title = "Supported but approximate (sparse data)";
      } else {
        td.textContent = "\u2014";
        td.className = "matrix-unsupported";
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  fetchAndMerge();
});
