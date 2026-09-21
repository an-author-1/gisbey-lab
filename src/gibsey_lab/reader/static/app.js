"use strict";

// Outcome states (exact ids, shared with reader/outcomes.py):
//   operator: not_requested | loading | selected | abstained | no_candidates | error
//   offers:   not_requested | loading | offers | no_qualified | no_candidates | atlas_incomplete | error
//
// Rules this file keeps:
// - An operator button shows ranked destinations from the saved atlas (GET
//   /api/operator-options): no provider work, never an empty unexplained panel, and
//   exploratory (weak-fit) options preview and follow exactly like supported ones.
// - Only three actions ever cause provider work, all explicit clicks: "Refine order using
//   my reading history" (POST /api/refine-options), "Ask Jev for a single pick (research)"
//   / "Ask Jev again" (POST /api/request-selection) and the advanced hand (POST
//   /api/offers). Page loads, refreshes, operator clicks and navigation only ever GET.
// - A single-pick abstention or error never hides or clears the ranked options, and
//   "Follow a single pick immediately" never follows a ranked option.
// - Every request carries a request_id. A response is rendered only if it is the latest
//   request for its key AND the reader is still on the same field/page/policy. Anything
//   else was still persisted by the server, but is not rendered and can never move the reader.
// - A rerun keeps the previous result on screen until the new one arrives, and earlier
//   results stay listed. One operator's result never clears another's, or the offers hand.
// - Corpus text is only ever placed with textContent.

const App = {
  field: null,
  policy: null,
  source: null,
  operator: null,
  criteria: {},          // operator -> exact criterion text, from /api/fields
  criteriaVersion: null,
  followImmediately: false,
  currentPage: null,     // {id, title, previous_id, next_id, sha256} for the active source
  navGeneration: 0,      // bumped on every page/field/policy change
  visitId: null,         // new random id per page visit; scopes follow tokens
  requestCounter: 0,
  latestRequest: {},     // request key -> newest request_id (an explicit rerun replaces it)
  inFlight: {},          // request key -> true while a POST is outstanding
  operatorResults: {},   // operator -> single-pick view, for the CURRENT page + policy only
  options: {},           // operator -> ranked option view, for the CURRENT page + policy only
  refine: {},            // operator -> {loading, message, state} of its history refinement
  offers: null,          // offers view for the current page + policy
  offersLoading: false,
  following: false,
  currentBond: null,     // {proposal_id, bond_id} of the route just followed
  followedRun: null,     // {run_dir} of the run just followed (optional note target)
  viewHistory: [],       // Back stack (also kept in sessionStorage so it survives reload)
  navLogged: Promise.resolve(),
  atlasSort: { column: "destination_id", direction: 1 },
  atlasData: null,
};

const el = (id) => document.getElementById(id);

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || `HTTP ${res.status}`);
    error.data = data;
    error.status = res.status;
    throw error;
  }
  return data;
}

function postJson(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

function randomId() {
  return Math.random().toString(36).slice(2, 10);
}

function newRequestId() {
  App.requestCounter += 1;
  return `req_${Date.now().toString(36)}_${App.requestCounter}_${randomId()}`;
}

function operatorKey(operator) {
  return ["operator", App.field, App.source, operator, App.policy, App.criteriaVersion].join("|");
}

function offersKey() {
  return ["offers", App.field, App.source, App.policy].join("|");
}

function snapshotContext() {
  return { generation: App.navGeneration, field: App.field, source: App.source, policy: App.policy };
}

function stillCurrent(ctx) {
  return ctx.generation === App.navGeneration && ctx.field === App.field &&
    ctx.source === App.source && ctx.policy === App.policy;
}

function logNavigation(event, extra) {
  // passive logging: never blocks or breaks the reading flow
  return postJson("/api/session/navigation", { event, field: App.field, policy: App.policy, ...extra }).catch(() => {});
}

function renderPassage(container, text) {
  container.replaceChildren();
  const paragraphs = String(text || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  for (const p of paragraphs) {
    const p2 = document.createElement("p");
    p2.textContent = p;
    container.appendChild(p2);
  }
}

function textNode(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

// --- Back stack persistence (per browser tab; never deletes anything server-side) ---

function saveViewHistory() {
  try { sessionStorage.setItem(`gibsey.back.${App.field}`, JSON.stringify(App.viewHistory)); } catch (e) { /* optional */ }
}

function loadViewHistory() {
  try {
    const stored = JSON.parse(sessionStorage.getItem(`gibsey.back.${App.field}`) || "[]");
    App.viewHistory = Array.isArray(stored) ? stored.filter((x) => typeof x === "string") : [];
  } catch (e) {
    App.viewHistory = [];
  }
  el("back-btn").disabled = App.viewHistory.length === 0;
}

// --- the viewer's chosen candidate policy survives a refresh (per browser, optional) ---

const POLICY_STORAGE_KEY = "gibsey.candidatePolicy";

function choosePolicy(stored, policies) {
  // The remembered choice if it is still a known policy; otherwise the server default.
  const known = (policies || []).map((p) => p.id);
  if (typeof stored === "string" && known.includes(stored)) return stored;
  const fallback = (policies || []).find((p) => p.default) || (policies || [])[0];
  return fallback ? fallback.id : null;
}

function readStoredPolicy() {
  try { return window.localStorage.getItem(POLICY_STORAGE_KEY); } catch (e) { return null; } // storage may be unavailable
}

function storePolicy(policy) {
  try { window.localStorage.setItem(POLICY_STORAGE_KEY, policy); } catch (e) { /* the page works without it */ }
}

async function init() {
  const fieldsData = await api("/api/fields");

  const fieldSelect = el("field-select");
  fieldSelect.replaceChildren();
  for (const f of fieldsData.fields) {
    const opt = document.createElement("option");
    opt.value = f.id;
    opt.textContent = f.label;
    if (f.default) opt.selected = true;
    fieldSelect.appendChild(opt);
  }
  App.field = fieldsData.fields.find((f) => f.default).id;

  const policySelect = el("policy-select");
  policySelect.replaceChildren();
  for (const p of fieldsData.policies) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.label;
    policySelect.appendChild(opt);
  }
  // Restored BEFORE the first page/option request, so nothing is ever fetched under a
  // policy the reader did not choose. No stored choice (or an unknown one) = server default.
  App.policy = choosePolicy(readStoredPolicy(), fieldsData.policies);
  policySelect.value = App.policy;

  App.criteria = fieldsData.criteria;
  App.criteriaVersion = fieldsData.default_criteria_version || null;
  renderOperatorButtons(fieldsData.operators, fieldsData.operator_version);

  fieldSelect.addEventListener("change", async () => {
    const previousField = App.field;
    App.field = fieldSelect.value;
    App.navGeneration++;
    App.viewHistory = [];
    saveViewHistory();
    el("back-btn").disabled = true;
    logNavigation("field_selected", { from_field: previousField });
    await checkFieldStatus();
    await loadPageList();
    const groups = el("page-select").querySelectorAll("optgroup");
    const firstPage = groups.length ? groups[0].querySelector("option").value : null;
    App.source = null;
    await navigateTo(firstPage, "dropdown");
  });
  policySelect.addEventListener("change", () => {
    App.policy = policySelect.value;
    storePolicy(App.policy);
    App.navGeneration++; // anything in flight under the old policy is now stale
    el("policy-badge").textContent = App.policy;
    // Results are policy-specific: clear what is DISPLAYED (the records stay on the server)
    // and re-read under the new policy, without moving the reader.
    App.operatorResults = {};
    App.options = {};
    App.refine = {};
    App.offers = null;
    App.offersLoading = false;
    updateOperatorBadges();
    renderOffers();
    loadLatestOffers();
    // Re-reading the saved atlas under the new policy is a GET; nothing is asked of Jev.
    if (App.operator) selectOperator(App.operator); else renderOperatorPanel();
  });
  el("back-btn").addEventListener("click", onBack);
  el("prev-btn").addEventListener("click", () => {
    if (App.currentPage && App.currentPage.previous_id) navigateTo(App.currentPage.previous_id, "previous");
  });
  el("next-btn").addEventListener("click", () => {
    if (App.currentPage && App.currentPage.next_id) navigateTo(App.currentPage.next_id, "next");
  });
  el("page-select").addEventListener("change", () => navigateTo(el("page-select").value, "dropdown"));
  el("follow-immediately-toggle").addEventListener("change", (e) => {
    App.followImmediately = e.target.checked;
  });
  el("request-new-btn").addEventListener("click", () => { if (App.operator) requestSelection(App.operator); });
  el("single-pick-button").addEventListener("click", () => singlePick(App.operator));
  el("refine-button").addEventListener("click", onRefineOptions);
  api("/api/build").then((b) => {
    el("build-id").textContent = `build ${(b.git_revision || "unknown").slice(0, 10)}${b.dirty ? " (uncommitted changes)" : ""} · app.js ${(b.app_js_sha256 || "").slice(0, 10)} · server started ${b.server_started_at}`;
    el("build-id").dataset.gitRevision = b.git_revision || "";
    el("build-id").dataset.appJsSha256 = b.app_js_sha256 || "";
  }).catch(() => {});
  el("accept-follow-btn").addEventListener("click", () => onAcceptAndFollow());
  el("offers-btn").addEventListener("click", onShowOffers);
  el("preserve-btn").addEventListener("click", onPreserve);
  el("save-note-btn").addEventListener("click", onSaveNote);
  el("atlas-details").addEventListener("toggle", () => { if (el("atlas-details").open) loadAtlas(); });
  el("atlas-mode").addEventListener("change", loadAtlas);

  await checkFieldStatus();
  await loadPageList();
  loadViewHistory();

  // Start where the reader actually was: the last page recorded in the session log, else
  // the recorded Q position, else the first page. Loading never requests anything from Jev.
  const readerState = await api("/api/reader-state");
  const last = readerState.last_viewed;
  let start = null;
  let via = "session_start";
  if (last && last.page_id && (!last.field || last.field === App.field)) {
    start = last.page_id;
    via = "reload";
  }
  if (!start) start = readerState.active_passage || readerState.active_page;
  if (start && !el("page-select").querySelector(`option[value="${CSS.escape(start)}"]`)) start = null;
  if (!start) {
    const firstGroup = el("page-select").querySelector("optgroup");
    start = firstGroup ? firstGroup.querySelector("option").value : null;
  }
  await navigateTo(start, via);
  renderTraversalHistory(readerState);
  // Reload: show again the operator list the reader had open on this page (a GET only).
  const lastOptions = readerState.last_operator_options;
  if (lastOptions && lastOptions.page_id === App.source && lastOptions.field === App.field &&
      lastOptions.policy === App.policy && lastOptions.operator) {
    await selectOperator(lastOptions.operator);
  }
}

async function checkFieldStatus() {
  const status = await api(`/api/field-status?field=${encodeURIComponent(App.field)}`);
  const banner = el("field-status-banner");
  if (status.ok) {
    banner.hidden = true;
    banner.textContent = "";
  } else {
    banner.hidden = false;
    banner.textContent = `Corpus problem in field "${App.field}": ${status.problems.join("; ")}`;
  }
}

async function loadPageList() {
  const data = await api(`/api/pages?field=${encodeURIComponent(App.field)}`);
  const pageSelect = el("page-select");
  pageSelect.replaceChildren();
  for (const group of data.groups) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.title;
    for (const id of group.pages) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = id;
      optgroup.appendChild(opt);
    }
    pageSelect.appendChild(optgroup);
  }
}

function renderOperatorButtons(operators, version) {
  const row = el("operator-buttons");
  row.replaceChildren();
  for (const op of operators) {
    const btn = document.createElement("button");
    btn.dataset.operator = op;
    btn.dataset.testid = `operator-${op}`;
    btn.title = `Q Operator Prototype ${version}`;
    btn.appendChild(textNode("span", op));
    btn.appendChild(textNode("span", "", "op-state"));
    btn.addEventListener("click", () => selectOperator(op));
    row.appendChild(btn);
  }
}

const BADGE_TEXT = { // the single-pick (research) state only; ranked options need no badge
  selected: (view) => `single pick: ${view.record.selected_id || ""}`,
  abstained: () => "single pick: NONE",
  no_candidates: () => "single pick: no candidates",
  error: () => "single pick: error",
  loading: () => "asking...",
};

function updateOperatorBadges() {
  document.querySelectorAll("#operator-buttons button").forEach((btn) => {
    const op = btn.dataset.operator;
    const view = App.operatorResults[op];
    btn.classList.toggle("active", op === App.operator);
    let text = "";
    if (view) {
      const label = view.loading ? BADGE_TEXT.loading : BADGE_TEXT[view.state];
      text = label ? label(view) : "";
    }
    btn.querySelector(".op-state").textContent = text;
  });
}

async function navigateTo(pageId, via) {
  if (!pageId) return;
  App.navGeneration++;
  const myGeneration = App.navGeneration;
  App.visitId = randomId();

  const previous = App.source;
  const isBack = via === "back";
  if (!isBack && previous && previous !== pageId) {
    App.viewHistory.push(previous);
    saveViewHistory();
  }
  el("back-btn").disabled = App.viewHistory.length === 0;

  // Displayed results belong to the page they were requested from. Leaving the page
  // clears what is SHOWN; every outcome stays recorded server-side and is listed again
  // under "Earlier results" when the reader returns.
  App.source = pageId;
  App.operator = null;
  App.operatorResults = {};
  App.options = {};
  App.refine = {};
  App.offers = null;
  App.offersLoading = false;
  App.currentBond = null;
  App.followedRun = null;

  el("page-select").value = pageId;
  const page = await api(`/api/page?field=${encodeURIComponent(App.field)}&id=${encodeURIComponent(pageId)}`);
  if (myGeneration !== App.navGeneration) return; // a newer navigation superseded this one

  App.currentPage = page;
  el("source-id").textContent = page.id;
  el("field-badge").textContent = App.field;
  el("policy-badge").textContent = App.policy;
  el("prev-btn").disabled = !page.previous_id;
  el("prev-btn").textContent = page.previous_id ? `← Previous (${page.previous_id})` : "← Previous";
  el("next-btn").disabled = !page.next_id;
  el("next-btn").textContent = page.next_id ? `Next (${page.next_id}) →` : "Next →";
  renderPassage(el("source-text"), page.text);

  el("operator-criterion").hidden = true;
  el("postfollow-panel").hidden = true;
  el("position-conflict").hidden = true;
  updateOperatorBadges();
  renderOptions();
  renderOperatorPanel();
  renderOffers();

  // A followed route's page view is logged by the server itself, in order, right after
  // the traversal; every other arrival is logged here.
  if (via !== "traversal") {
    App.navLogged = logNavigation(isBack ? "back" : "page_viewed", {
      page_id: pageId, from_page: previous && previous !== pageId ? previous : null, via: via || "dropdown",
    });
  }
  loadLatestOffers();
  if (el("atlas-details").open) loadAtlas();
}

async function onBack() {
  if (App.viewHistory.length === 0) return;
  const prev = App.viewHistory.pop();
  saveViewHistory();
  await navigateTo(prev, "back");
}

// --- operator requests ---

function flattenSelectionRecord(record) {
  // /api/request-selection nests the validated outcome under `result`; /api/saved-result is flat.
  const result = record.result || {};
  return {
    run_id: record.run_id, run_dir: record.run_dir, field: record.field, source: record.source,
    operator: record.operator, criterion: record.criterion,
    selected_id: record.selected_id !== undefined ? record.selected_id : result.selected_id,
    selected_text: record.selected_text !== undefined ? record.selected_text : result.selected_text,
    confidence: record.confidence !== undefined ? record.confidence : result.confidence,
    probabilities: record.probabilities !== undefined ? record.probabilities : result.probabilities,
    requested_model: record.requested_model, returned_model: record.returned_model,
    elapsed_seconds: record.elapsed_seconds, usage: record.usage, error: record.error,
    candidate_count: record.candidate_count, policy: record.policy, criteria_version: record.criteria_version,
    page_sha256: record.page_sha256, request_id: record.request_id, request_ids: record.request_ids,
    outcome_id: record.outcome_id, joined: record.joined,
  };
}

function operatorView(record, provenance) {
  return {
    state: record.state || "error",
    message: record.message || (record.error ? `The request failed and nothing was selected: ${record.error}` : ""),
    provenance,
    record: flattenSelectionRecord(record),
    loading: false,
  };
}

async function selectOperator(operator) {
  // An operator click shows ranked destinations from the saved atlas. It never asks Jev.
  if (App.operator !== operator) {
    el("earlier-list").replaceChildren();
    el("earlier-count").textContent = "0";
  }
  App.operator = operator;
  el("operator-criterion").hidden = false;
  el("operator-criterion").textContent = App.criteria[operator] || "";
  el("postfollow-panel").hidden = true;
  updateOperatorBadges();
  renderOptions();
  renderOperatorPanel();
  loadEarlier(operator);
  if (!App.options[operator]) await loadOptions(operator);
}

async function loadOptions(operator) {
  const ctx = snapshotContext();
  App.options[operator] = { loading: true };
  if (App.operator === operator) renderOptions();
  let data;
  try {
    data = await api(
      `/api/operator-options?field=${encodeURIComponent(ctx.field)}&page=${encodeURIComponent(ctx.source)}` +
      `&operator=${encodeURIComponent(operator)}&policy=${encodeURIComponent(ctx.policy)}`
    );
  } catch (e) {
    data = { state: "error", options: [], counts: {}, message: `The ranked destinations could not be loaded: ${e.message}. Previous, Next and the page list still work; click the operator again to retry.`, ordering_line: "" };
  }
  if (!stillCurrent(ctx)) return;
  App.options[operator] = data;
  if (data.state === "error") delete App.options[operator].option_set_id;
  if (App.operator === operator) renderOptions();
  if (data.state === "error") delete App.options[operator]; // a later click retries
}

const CAUTION_TEXT = {
  low_confidence: "low confidence in this assessment",
  high_redundancy: "may largely repeat this page",
  high_missing_context: "may need context you have not read",
  low_direct_q_fit: "weak direct fit as a next page",
};

function fitLine(operator, fit, fitLevel) {
  if (!fit) return `${operator} fit: not available`;
  // The word is the rubric level this score CLEARS (from the server), never a rounded one,
  // so an exploratory row cannot carry a word a supported row carries. Numbers untouched.
  const level = fitLevel && fitLevel.name ? fitLevel.name : null;
  const score = typeof fit.score === "number" ? `${Math.round(fit.score * 100) / 100} of 3` : "no score";
  const confidence = typeof fit.confidence === "number" ? `, confidence ${Math.round(fit.confidence * 100) / 100}` : "";
  return `${operator} fit (${fit.dimension || "base assessment"}): ${level ? `${level} — ` : ""}${score}${confidence}`;
}

function optionDetails(data, option) {
  const base = {};
  for (const [dim, value] of Object.entries(option.base || {})) {
    base[dim] = value && typeof value === "object" ? { score: value.score, confidence: value.confidence } : value;
  }
  const details = {
    rank: option.rank, tier: option.tier, operator_fit: option.operator_fit, cautions: option.cautions,
    base_profile_scores: base, base_assessment_id: option.assessment_id,
    is_authored_neighbor: option.is_authored_neighbor, rank_reasons: option.rank_reasons,
    option_set_id: data.option_set_id, ordering_basis: data.ordering_basis, counts: data.counts,
    atlas_mode: data.mode, atlas_config_id: data.atlas_config_id, destination_sha256: option.destination_sha256,
  };
  if (option.contextual) details.history_conditioned_answers = option.contextual;
  if (option.contextual_error) details.history_refinement_error = option.contextual_error;
  return details;
}

function renderOptionRow(data, option, position) {
  const display = (data.reader_display || {})[option.destination_id] || {};
  const row = document.createElement("div");
  row.className = "option-row";
  row.dataset.testid = "option-row";
  row.dataset.destination = option.destination_id;
  row.dataset.tier = option.tier || "";

  const heading = document.createElement("h3");
  heading.appendChild(textNode("span", `${position}.`, "option-rank"));
  heading.appendChild(textNode("span", option.destination_id, "page-tag"));
  heading.appendChild(textNode("span", display.title ? `  ${display.title}` : "", "offer-title"));
  row.appendChild(heading);

  const tierLabel = option.tier_label || (option.tier === "supported" ? "Supported" : "Exploratory — weak or uncertain fit");
  const badge = textNode("span", tierLabel, `tier-badge tier-${option.tier === "supported" ? "supported" : "exploratory"}`);
  badge.dataset.testid = "option-tier";
  row.appendChild(badge);
  if (option.is_authored_neighbor) row.appendChild(textNode("span", "authored neighbor", "relation-label"));
  row.appendChild(textNode("div", fitLine(data.operator, option.operator_fit, option.fit_level), "option-fit"));
  const cautions = document.createElement("div");
  for (const caution of option.cautions || []) {
    const chip = textNode("span", CAUTION_TEXT[caution] || caution, "caution-chip");
    chip.dataset.caution = caution;
    cautions.appendChild(chip);
  }
  row.appendChild(cautions);

  const preview = document.createElement("div");
  preview.className = "passage offer-preview";
  preview.dataset.testid = "option-preview-text";
  preview.hidden = true;
  row.appendChild(preview);

  const actions = document.createElement("div");
  actions.className = "action-row";
  const previewBtn = textNode("button", "Preview");
  previewBtn.dataset.testid = "option-preview";
  previewBtn.addEventListener("click", () => {
    preview.hidden = !preview.hidden;
    previewBtn.textContent = preview.hidden ? "Preview" : "Hide preview";
    if (preview.hidden) return;
    if (typeof display.text === "string") renderPassage(preview, display.text); // the exact recorded page text
    else preview.replaceChildren(textNode("p", "This page has changed since it was assessed, so its text is not shown here.", "stale-note"));
    logNavigation("offer_previewed", { page_id: App.source, destination_id: option.destination_id, option_set_id: data.option_set_id, via: "option_row" });
  });
  const followBtn = textNode("button", "Follow →");
  followBtn.dataset.testid = "option-follow";
  followBtn.disabled = App.following || display.version_matches === false;
  followBtn.addEventListener("click", () => onFollowOption(data, option));
  actions.appendChild(previewBtn);
  actions.appendChild(followBtn);
  row.appendChild(actions);

  const details = document.createElement("details");
  details.appendChild(textNode("summary", "Details (all seven base dimensions, ids, counts)"));
  details.appendChild(textNode("pre", JSON.stringify(optionDetails(data, option), null, 2)));
  row.appendChild(details);
  return row;
}

function renderOptions() {
  const operator = App.operator;
  const block = el("options-block");
  if (!operator) {
    block.hidden = true;
    return;
  }
  block.hidden = false;
  const data = App.options[operator] || { loading: true };
  const list = el("options-list");
  const statusEl = el("options-status");
  const refine = App.refine[operator] || {};
  list.replaceChildren();
  list.dataset.operator = operator;
  list.dataset.page = App.source || "";
  list.dataset.orderingBasis = data.ordering_basis || "";
  list.dataset.optionSetId = data.option_set_id || "";
  list.dataset.state = data.loading ? "loading" : (data.state || "");
  list.dataset.orderChanged = data.order_changed === true ? "true" : "false";

  if (data.loading) {
    statusEl.className = "status-line status-loading";
    statusEl.textContent = "Reading the saved atlas...";
    el("ordering-line").textContent = "";
    el("refine-button").disabled = true;
    el("refine-status").textContent = "";
    el("options-details").hidden = true;
    return;
  }
  // Success green only when every shown option is supported and nothing was left out;
  // none supported is informational (never green); a mix is the in-between style.
  const shownSupported = (data.options || []).filter((o) => o.tier === "supported").length;
  const shownTotal = (data.options || []).length;
  let statusClass = "state-info";
  if (data.state === "options" && shownSupported > 0) {
    statusClass = shownSupported === shownTotal && !((data.counts || {}).unusable > 0) ? "state-selected" : "state-mixed";
  }
  statusEl.className = `status-line ${statusClass}`;
  statusEl.dataset.supportedShown = String(shownSupported);
  statusEl.textContent = data.message || data.state || "";
  el("ordering-line").textContent = data.ordering_line || "";

  (data.options || []).forEach((option, index) => list.appendChild(renderOptionRow(data, option, index + 1)));

  const canRefine = (data.options || []).length > 0 && !!data.option_set_id;
  el("refine-button").hidden = !canRefine;
  el("refine-button").disabled = !!refine.loading;
  el("refine-button").textContent = refine.state && !String(refine.state).startsWith("refined") ? "Try the history refinement again" : "Refine order using my reading history";
  const refineStatus = el("refine-status");
  const refineClass = { refined: "state-selected", refined_unchanged: "state-info" }[refine.state] || (refine.state ? "state-error" : "");
  refineStatus.className = `status-line ${refine.loading ? "status-loading" : refineClass}`;
  refineStatus.dataset.state = refine.loading ? "loading" : (refine.state || "");
  refineStatus.textContent = refine.loading ? "Comparing these options with your reading history... they stay usable meanwhile." : (refine.message || "");

  el("options-details").hidden = false;
  el("options-details-body").textContent = JSON.stringify({
    state: data.state, operator: data.operator, dimension: data.dimension, policy: data.policy,
    ordering_basis: data.ordering_basis, counts: data.counts, could_not_be_ranked: data.unusable,
    support_floor: data.support_floor, atlas_mode: data.mode, atlas_config_id: data.atlas_config_id,
    option_set_id: data.option_set_id, page_sha256: data.page_sha256, refinement: data.refinement,
  }, null, 2);
}

async function onRefineOptions() {
  const operator = App.operator;
  const shown = App.options[operator];
  if (!operator || !shown || !shown.option_set_id) return;
  const key = ["refine", App.field, App.source, operator, App.policy, shown.option_set_id].join("|");
  if (App.inFlight[key]) return;
  const ctx = snapshotContext();
  const requestId = newRequestId();
  App.latestRequest[key] = requestId;
  App.inFlight[key] = true;
  App.refine[operator] = { loading: true };
  if (App.operator === operator) renderOptions(); // the list stays exactly as it is, and usable

  let data;
  try {
    await App.navLogged;
    data = await postJson("/api/refine-options", { option_set_id: shown.option_set_id, request_id: requestId });
  } catch (e) {
    data = e.data && e.data.refine_state ? e.data : { refine_state: "error", refine_message: `History refinement could not run; the base order is kept and every option stays usable. ${e.message} You can try again.` };
    if (stillCurrent(ctx) && showPositionConflict(e)) {
      data = { ...data, refine_message: "Not refined: choose above whether to continue on this page. The base order is kept and every option stays usable." };
    }
  } finally {
    delete App.inFlight[key];
  }

  // Apply only if the reader is still on the same page/policy, this is the newest request,
  // it is for the list still shown, and the server says the history has not changed.
  if (!stillCurrent(ctx)) return; // persisted server-side; ignored here
  if (App.latestRequest[key] !== requestId) return;
  if (data.request_id && data.request_id !== requestId) return;
  const current = App.options[operator];
  if (!current || current.option_set_id !== shown.option_set_id) return;

  const usable = data.refine_state === "refined" && data.applicable !== false && data.memory_current !== false &&
    Array.isArray(data.options) && data.options.length === (current.options || []).length;
  if (usable) {
    App.options[operator] = data;
    App.refine[operator] = { state: data.order_changed ? "refined" : "refined_unchanged", message: data.refine_message };
  } else {
    // Keep the base list untouched; say plainly that it was NOT newly assessed.
    const stale = data.refine_state === "refined";
    App.options[operator] = { ...current, ordering_line: stale ? current.ordering_line : (data.ordering_line || current.ordering_line) };
    App.refine[operator] = {
      state: stale ? "superseded" : (data.refine_state || "error"),
      message: stale ? "Your reading history changed while this ran, so the refinement was not applied; the base order is kept. You can try again." : (data.refine_message || "History refinement did not complete; the base order is kept. You can try again."),
    };
  }
  if (App.operator === operator) renderOptions();
}

async function onFollowOption(data, option) {
  if (App.following) return;
  // A list belongs to the page it was computed for; never follow it from anywhere else.
  if (data.page_id !== App.source || data.field !== App.field) return;
  const ctx = snapshotContext();
  App.following = true;
  renderOptions();
  try {
    await App.navLogged;
    const outcome = await postJson("/api/follow-option", {
      option_set_id: data.option_set_id, destination_id: option.destination_id,
      from_page: ctx.source, client_page: ctx.source, ordering_basis: data.ordering_basis,
      follow_token: `${App.visitId}:${data.option_set_id}:${option.destination_id}`,
    });
    if (!stillCurrent(ctx)) return;
    App.following = false;
    await afterFollow(outcome, outcome.destination || option.destination_id, null);
  } catch (e) {
    if (stillCurrent(ctx)) {
      App.following = false;
      renderOptions();
      if (!showPositionConflict(e)) {
        el("options-status").className = "status-line state-error";
        el("options-status").textContent = `Not followed — you have not moved. ${e.message}`;
      }
    }
  } finally {
    App.following = false;
  }
}

// --- second tab: the session log places the reader on another page ---

function showPositionConflict(error) {
  // Nothing has moved. Offer the two honest choices; never a reload (that would silently
  // move this tab to the other tab's page). "Continue here" does ONLY what it says: it
  // records that the reader is on this tab's page and clears the banner. It never replays
  // the refused action -- no follow, no dispatch. The reader clicks Follow/Refine again.
  const conflict = error && error.data && error.data.position_conflict;
  if (!conflict) return false;
  const box = el("position-conflict");
  box.replaceChildren();
  box.hidden = false;
  box.appendChild(textNode("p", error.message));
  const actions = document.createElement("div");
  actions.className = "action-row";
  const here = textNode("button", `Continue here on ${conflict.this_page}`);
  here.dataset.testid = "conflict-continue-here";
  here.addEventListener("click", async () => {
    here.disabled = true;
    App.navLogged = logNavigation("page_viewed", { page_id: App.source, via: "resume" });
    await App.navLogged;
    box.hidden = true;
    if (App.operator) delete App.refine[App.operator]; // drop the "choose above" note; the list itself is untouched
    renderOptions();
    renderOffers();
    renderOperatorPanel();
  });
  actions.appendChild(here);
  if (conflict.logged_page) {
    const go = textNode("button", `Go to ${conflict.logged_page}`);
    go.dataset.testid = "conflict-go-to-other";
    go.addEventListener("click", () => {
      box.hidden = true;
      navigateTo(conflict.logged_page, "dropdown");
    });
    actions.appendChild(go);
  }
  box.appendChild(actions);
  box.scrollIntoView({ block: "center" });
  return true;
}

// --- single pick (research): the secondary, explicit Choice request ---

async function singlePick(operator) {
  // Explicit click only. Shows a matching recorded pick if one exists, otherwise makes one
  // live request. Whatever it returns, the ranked options above are untouched.
  if (!operator) return;
  if (App.operatorResults[operator] && App.operatorResults[operator].loading) return;

  const ctx = snapshotContext();
  App.operatorResults[operator] = { state: "loading", phase: "lookup", loading: true, record: {} };
  updateOperatorBadges();
  renderOperatorPanel();

  let saved;
  try {
    saved = await api(
      `/api/saved-result?field=${encodeURIComponent(ctx.field)}&source=${encodeURIComponent(ctx.source)}` +
      `&operator=${encodeURIComponent(operator)}&policy=${encodeURIComponent(ctx.policy)}`
    );
  } catch (e) {
    if (!stillCurrent(ctx)) return;
    App.operatorResults[operator] = operatorView({ state: "error", error: e.message, source: ctx.source, field: ctx.field, operator }, "lookup");
    updateOperatorBadges();
    renderOperatorPanel();
    loadEarlier(operator);
    return;
  }
  if (!stillCurrent(ctx)) return; // stale: field/page/policy changed since this click

  if (saved.recorded) {
    App.operatorResults[operator] = operatorView(saved, "recorded");
    updateOperatorBadges();
    if (App.operator === operator) {
      renderOperatorPanel();
      loadEarlier(operator);
    }
    // A recorded pick is followed automatically only if it is for exactly this page.
    if (App.followImmediately && App.operator === operator && saved.source === App.source && saved.field === App.field) {
      await onAcceptAndFollow(true);
    }
  } else {
    delete App.operatorResults[operator];
    await requestSelection(operator);
  }
}

async function requestSelection(operator) {
  const key = operatorKey(operator);
  if (App.inFlight[key]) return; // a duplicate click joins nothing client-side: the button is disabled

  const ctx = snapshotContext();
  const requestId = newRequestId();
  App.latestRequest[key] = requestId; // an explicit rerun always becomes the newest request
  App.inFlight[key] = true;

  // Keep whatever was on screen; only mark it as being refreshed.
  const previous = App.operatorResults[operator];
  App.operatorResults[operator] = previous && previous.state !== "loading"
    ? { ...previous, loading: true }
    : { state: "loading", loading: true, record: {} };
  updateOperatorBadges();
  renderOperatorPanel();

  let record;
  try {
    record = await postJson("/api/request-selection", {
      field: ctx.field, source: ctx.source, operator, policy: ctx.policy,
      version: App.criteriaVersion || undefined, request_id: requestId,
    });
  } catch (e) {
    // The server persists failures too; show the same error state it recorded.
    record = e.data && e.data.state ? e.data : { state: "error", error: e.message, request_id: requestId };
    if (!record.error) record.error = e.message;
  } finally {
    delete App.inFlight[key];
  }

  // Apply only the latest request for the page still on screen. Otherwise the outcome is
  // already persisted server-side and will appear under "Earlier results" -- but it is
  // not rendered here and can never trigger movement.
  if (!stillCurrent(ctx)) return;
  if (App.latestRequest[key] !== requestId) return;
  if (record.request_id && record.request_id !== requestId) return;

  const provenance = record.kind === "mock" ? "mock" : "new";
  App.operatorResults[operator] = operatorView({ source: ctx.source, field: ctx.field, operator, ...record }, provenance);
  updateOperatorBadges();
  if (App.operator === operator) {
    renderOperatorPanel();
    loadEarlier(operator);
  }

  const view = App.operatorResults[operator];
  if (App.followImmediately && App.operator === operator && view.state === "selected" &&
      record.applicable !== false && view.record.source === App.source && view.record.field === App.field) {
    await onAcceptAndFollow(true);
  }
}

const PROVENANCE_LABEL = {
  recorded: "Recorded result",
  new: "New live result (just requested)",
  mock: "MOCK result (not a real Jev call)",
  lookup: "Lookup",
};

function renderOperatorPanel() {
  const operator = App.operator;
  const panel = el("result-panel");
  if (!operator) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  el("result-operator").textContent = operator;

  const view = App.operatorResults[operator] || { state: "not_requested", record: {}, loading: false };
  const statusEl = el("result-status");
  const bodyEl = el("result-body");
  const hasResult = view.state !== "loading" && view.state !== "not_requested";

  el("result-loading").hidden = !(view.loading && hasResult);
  statusEl.replaceChildren();
  if (view.state === "loading") {
    statusEl.className = "status-line status-loading";
    statusEl.textContent = view.phase === "lookup" ? "Loading — checking for a recorded result..." : "Loading — asking Jev...";
  } else if (view.state === "not_requested") {
    statusEl.className = "status-line state-not_requested";
    statusEl.textContent = "No single pick requested on this visit.";
  } else {
    statusEl.className = `status-line state-${view.state}`;
    statusEl.appendChild(textNode("span", view.message));
    statusEl.appendChild(textNode("span", ` — ${PROVENANCE_LABEL[view.provenance] || view.provenance}`, "kind-note"));
  }

  bodyEl.replaceChildren();
  if (view.state === "selected") {
    bodyEl.appendChild(textNode("h3", view.record.selected_id || ""));
    const passageDiv = document.createElement("div");
    passageDiv.className = "passage";
    renderPassage(passageDiv, view.record.selected_text);
    bodyEl.appendChild(passageDiv);
  }

  el("tech-details").hidden = !hasResult;
  if (hasResult) {
    el("tech-details-body").textContent = JSON.stringify({ state: view.state, provenance: view.provenance, ...view.record, selected_text: undefined }, null, 2);
  }

  el("result-actions").hidden = !hasResult;
  el("earlier-results").hidden = false;
  el("single-pick-button").hidden = hasResult;
  el("single-pick-button").disabled = !!view.loading;
  el("request-new-btn").textContent = "Ask Jev again";
  el("request-new-btn").disabled = !!view.loading;
  el("accept-follow-btn").disabled = !!view.loading || App.following || view.state !== "selected" || !view.record.run_dir;
}

async function loadEarlier(operator) {
  const ctx = snapshotContext();
  let data;
  try {
    data = await api(
      `/api/outcomes?field=${encodeURIComponent(ctx.field)}&page=${encodeURIComponent(ctx.source)}` +
      `&operator=${encodeURIComponent(operator)}&policy=${encodeURIComponent(ctx.policy)}` +
      (App.criteriaVersion ? `&version=${encodeURIComponent(App.criteriaVersion)}` : "")
    );
  } catch (e) {
    return; // the list is supplementary; the current result stays as it is
  }
  if (!stillCurrent(ctx) || App.operator !== operator) return;

  const shown = (App.operatorResults[operator] || {}).record || {};
  const list = el("earlier-list");
  list.replaceChildren();
  let count = 0;
  for (const outcome of data.outcomes) {
    const isShown = (shown.outcome_id && outcome.outcome_id === shown.outcome_id) ||
      (shown.run_dir && outcome.run_dir === shown.run_dir);
    if (isShown) continue;
    count += 1;
    const item = document.createElement("li");
    item.appendChild(textNode("span", outcome.message || outcome.state, `state-${outcome.state}`));
    const when = outcome.at ? new Date(outcome.at).toLocaleString() : "time unknown";
    const where = outcome.run_id || (outcome.run_dir ? outcome.run_dir.split("/").pop() : "no run recorded");
    item.appendChild(textNode("span", `${when} · ${outcome.source === "recorded" ? "recorded run" : "requested here"} · ${outcome.state} · ${where}`, "earlier-meta"));
    list.appendChild(item);
  }
  el("earlier-count").textContent = String(count);
}

// --- following (the only thing that moves the reader) ---

async function afterFollow(outcome, destination, runDir) {
  App.currentBond = { proposal_id: outcome.proposal_id, bond_id: outcome.bond_id };
  const bond = App.currentBond;
  renderTraversalHistory(outcome.reader_state);
  await navigateTo(destination, "traversal");
  App.currentBond = bond;
  App.followedRun = runDir ? { run_dir: runDir } : null;

  el("postfollow-panel").hidden = false;
  el("postfollow-id").textContent = destination;
  el("preserve-status").textContent = "";
  el("note-status").textContent = "";
  // The optional note is stored with a recorded run; a followed offer has no run to hold one.
  el("save-note-btn").closest("details").hidden = !runDir;
  ["note-correspondence", "note-change"].forEach((id) => (el(id).value = ""));
  ["note-grounding", "note-effect", "note-decision"].forEach((id) => (el(id).value = ""));
}

async function onAcceptAndFollow(automatic) {
  const operator = App.operator;
  const view = App.operatorResults[operator];
  if (App.following || !view || view.loading || view.state !== "selected" || !view.record.run_dir) return;
  // Never follow a result that belongs to another page or field.
  if (view.record.source !== App.source || view.record.field !== App.field) return;

  const ctx = snapshotContext();
  App.following = true;
  renderOperatorPanel();
  if (automatic) el("result-loading").hidden = false;
  try {
    await App.navLogged;
    const outcome = await postJson("/api/accept-and-follow", {
      run_dir: view.record.run_dir, field: ctx.field, source: ctx.source, operator,
      from_page: ctx.source, client_page: ctx.source,
      follow_token: `${App.visitId}:${view.record.run_id || view.record.run_dir}`,
    });
    if (!stillCurrent(ctx)) return; // a newer navigation superseded this
    App.following = false;
    await afterFollow(outcome, outcome.destination || view.record.selected_id, view.record.run_dir);
  } catch (e) {
    if (stillCurrent(ctx)) {
      const statusEl = el("result-status");
      statusEl.className = "status-line state-error";
      statusEl.textContent = `Not followed — you have not moved. ${e.message}`;
      showPositionConflict(e);
    }
  } finally {
    App.following = false;
    if (stillCurrent(ctx)) renderOperatorPanelButtonsOnly();
  }
}

function renderOperatorPanelButtonsOnly() {
  const view = App.operatorResults[App.operator];
  if (!view) return;
  el("request-new-btn").disabled = !!view.loading;
  el("accept-follow-btn").disabled = !!view.loading || App.following || view.state !== "selected" || !view.record.run_dir;
}

// --- offers: a small hand of possible next pages ---

async function loadLatestOffers() {
  // Read-only: shows the last persisted hand for this page after a refresh. Never dispatches.
  const ctx = snapshotContext();
  let data;
  try {
    data = await api(`/api/offers/latest?field=${encodeURIComponent(ctx.field)}&page=${encodeURIComponent(ctx.source)}&policy=${encodeURIComponent(ctx.policy)}`);
  } catch (e) {
    return;
  }
  if (!stillCurrent(ctx) || App.offers || App.offersLoading) return; // never overwrite a fresher hand
  if (data.found) {
    App.offers = data;
    renderOffers();
  }
}

async function onShowOffers() {
  const key = offersKey();
  if (App.inFlight[key]) return;
  const ctx = snapshotContext();
  const requestId = newRequestId();
  App.latestRequest[key] = requestId;
  App.inFlight[key] = true;
  App.offersLoading = true;
  renderOffers(); // the previous hand, if any, stays visible while loading

  let data;
  try {
    await App.navLogged; // the arrival at this page must be in the log the memory packet is built from
    const intention = el("intention-input").value.trim();
    data = await postJson("/api/offers", {
      field: ctx.field, page: ctx.source, policy: ctx.policy, request_id: requestId,
      intention: intention || undefined,
    });
  } catch (e) {
    data = e.data && e.data.state ? e.data : { state: "error", message: `The offer request failed and no routes are shown: ${e.message}`, offers: [] };
    if (stillCurrent(ctx)) showPositionConflict(e);
  } finally {
    delete App.inFlight[key];
  }

  if (!stillCurrent(ctx)) return; // persisted server-side; not rendered for a page the reader has left
  if (App.latestRequest[key] !== requestId) return;
  if (data.request_id && data.request_id !== requestId) return;
  App.offersLoading = false;
  App.offers = data;
  renderOffers();
}

function scoreOf(value) {
  if (value && typeof value === "object") return value.score;
  return value;
}

function offerDetails(data, offer) {
  const base = (offer.base && (offer.base.dimensions || offer.base)) || {};
  const baseScores = {};
  for (const [dim, value] of Object.entries(base)) {
    if (value && typeof value === "object") baseScores[dim] = { score: value.score, confidence: value.confidence };
    else if (typeof value === "number") baseScores[dim] = value;
  }
  const contextual = offer.contextual || {};
  const answers = contextual.answers || contextual;
  const contextualScores = {};
  for (const [qid, value] of Object.entries(answers)) {
    if (value && typeof value === "object" && ("score" in value || "confidence" in value)) {
      contextualScores[qid] = { score: value.score, confidence: value.confidence };
    }
  }
  const versions = data.versions || {};
  return {
    rank: offer.rank,
    computed_for_current_reading_history: data.memory_current,
    base_profile_scores: baseScores,
    [data.memory_current === false ? "answers_conditioned_on_an_EARLIER_history" : "history_conditioned_answers"]: contextualScores,
    contextual_from_cache: offer.from_cache,
    rank_reasons: offer.rank_reasons,
    is_authored_neighbor: offer.is_authored_neighbor,
    mode: data.mode,
    requested_model: versions.requested_model,
    returned_model: contextual.returned_model || versions.returned_models,
    usage_for_this_hand: data.usage,
    memory: data.memory_summary,
    offer_set_id: data.offer_set_id,
    contextual_assessment_id: offer.contextual_assessment_id,
    base_assessment_id: offer.base && offer.base.assessment_id,
    request_ids: data.request_ids,
    outcome_id: data.outcome_id,
    destination_sha256: offer.destination_sha256,
  };
}

const PREVIEW_CHARS = 400;

function renderOfferCard(data, offer) {
  // A hand computed for an earlier reading history is shown for reference only.
  const outdated = data.memory_current === false;
  const card = document.createElement("div");
  card.className = outdated ? "offer-card offer-card-outdated" : "offer-card";
  const display = (data.reader_display || {})[offer.destination_id] || {};

  const heading = document.createElement("h3");
  heading.appendChild(textNode("span", offer.destination_id, "page-tag"));
  heading.appendChild(textNode("span", display.title ? `  ${display.title}` : "", "offer-title"));
  card.appendChild(heading);

  const labels = document.createElement("div");
  for (const label of offer.relation_labels || []) labels.appendChild(textNode("span", label, "relation-label"));
  card.appendChild(labels);

  const preview = document.createElement("div");
  preview.className = "passage offer-preview";
  const fullText = display.text;
  let expanded = false;
  const drawPreview = () => {
    if (typeof fullText !== "string") {
      preview.replaceChildren(textNode("p", "This page has changed since it was assessed, so its text is not shown here.", "stale-note"));
    } else if (expanded || fullText.length <= PREVIEW_CHARS) {
      renderPassage(preview, fullText);
    } else {
      renderPassage(preview, `${fullText.slice(0, PREVIEW_CHARS).trimEnd()} …`);
    }
  };
  drawPreview();
  card.appendChild(preview);

  const actions = document.createElement("div");
  actions.className = "action-row";
  const previewBtn = textNode("button", "Preview full page");
  previewBtn.disabled = typeof fullText !== "string";
  previewBtn.addEventListener("click", () => {
    expanded = !expanded;
    previewBtn.textContent = expanded ? "Show less" : "Preview full page";
    drawPreview();
    if (expanded) {
      logNavigation("offer_previewed", { page_id: App.source, destination_id: offer.destination_id, offer_set_id: data.offer_set_id, via: "offer_card" });
    }
  });
  const followBtn = textNode("button", "Follow →", "follow-offer-btn");
  followBtn.disabled = outdated || App.following || App.offersLoading || display.version_matches === false;
  if (outdated) followBtn.title = "Ask again first: this hand was computed for an earlier reading history.";
  followBtn.addEventListener("click", () => onFollowOffer(data, offer));
  actions.appendChild(previewBtn);
  actions.appendChild(followBtn);
  card.appendChild(actions);

  const details = document.createElement("details");
  details.appendChild(textNode("summary", outdated
    ? "Details of the EARLIER computation (its history-conditioned answers are not current)"
    : "Details (scores, confidence, provenance, memory, model, usage)"));
  details.appendChild(textNode("pre", JSON.stringify(offerDetails(data, offer), null, 2)));
  card.appendChild(details);
  return card;
}

function renderOffers() {
  const statusEl = el("offers-status");
  const cardsEl = el("offers-cards");
  const data = App.offers;
  el("offers-loading").hidden = !App.offersLoading;
  el("offers-btn").disabled = App.offersLoading;
  const outdated = !!data && data.memory_current === false;
  el("offers-btn").textContent = data && !outdated ? "Ask again for possible next pages" : "Show possible next pages";

  statusEl.replaceChildren();
  cardsEl.replaceChildren();
  if (!data) {
    statusEl.className = "status-line state-not_requested";
    statusEl.textContent = App.offersLoading ? "" : "Not requested yet for this page.";
    return;
  }
  statusEl.className = outdated ? "status-line state-outdated" : `status-line state-${data.state}`;
  if (outdated) {
    statusEl.appendChild(textNode("strong", `${data.memory_note || "Computed for an earlier reading history — ask again for routes informed by how you got here this time"}. `));
  }
  statusEl.appendChild(textNode("span", data.message || data.state));
  const notes = [];
  if (data.mode === "mock") notes.push("MOCK assessments (deterministic stand-in, not Jev)");
  if (data.from_store) notes.push(`saved hand from ${data.at ? new Date(data.at).toLocaleString() : "earlier"}; nothing was requested just now`);
  if (data.stale) notes.push("a page in this hand has changed since it was assessed");
  if (notes.length) statusEl.appendChild(textNode("span", ` — ${notes.join("; ")}`, "kind-note"));

  if (data.state === "offers") {
    for (const offer of (data.offers || []).slice(0, 3)) cardsEl.appendChild(renderOfferCard(data, offer));
  }
}

async function onFollowOffer(data, offer) {
  if (App.following) return;
  // A hand belongs to the page it was computed for; never follow it from anywhere else.
  if (data.page_id !== App.source || data.field !== App.field) return;
  const ctx = snapshotContext();
  App.following = true;
  renderOffers();
  try {
    await App.navLogged;
    const outcome = await postJson("/api/follow-offer", {
      offer_set_id: data.offer_set_id, destination_id: offer.destination_id,
      from_page: ctx.source, client_page: ctx.source,
      follow_token: `${App.visitId}:${data.offer_set_id}:${offer.destination_id}`,
    });
    if (!stillCurrent(ctx)) return;
    App.following = false;
    await afterFollow(outcome, outcome.destination || offer.destination_id, null);
  } catch (e) {
    if (stillCurrent(ctx)) {
      App.following = false;
      if (e.data && e.data.memory_current === false && App.offers) App.offers = { ...App.offers, memory_current: false };
      renderOffers();
      showPositionConflict(e);
      const statusEl = el("offers-status");
      statusEl.appendChild(textNode("span", ` Not followed — you have not moved. ${e.message}`, "state-error"));
    }
  } finally {
    App.following = false;
  }
}

// --- atlas inspection: the active page's 40 base pair profiles ---

async function loadAtlas() {
  const ctx = snapshotContext();
  const mode = el("atlas-mode").value;
  el("atlas-coverage").textContent = "Loading profiles...";
  let data;
  try {
    data = await api(`/api/atlas/profiles?source=${encodeURIComponent(ctx.source)}&mode=${encodeURIComponent(mode)}`);
  } catch (e) {
    if (stillCurrent(ctx)) {
      el("atlas-coverage").textContent = `Profiles unavailable: ${e.message}`;
      el("atlas-table").replaceChildren();
    }
    return;
  }
  if (!stillCurrent(ctx)) return;
  App.atlasData = data;
  renderAtlas();
}

function renderAtlas() {
  const data = App.atlasData;
  const table = el("atlas-table");
  table.replaceChildren();
  if (!data) return;
  el("atlas-mode-label").textContent = data.label || data.mode;
  if (!data.available) {
    el("atlas-coverage").textContent = data.message || "The atlas is not available.";
    return;
  }
  const c = data.counts || {};
  el("atlas-coverage").textContent =
    `${data.source}: ${c.complete || 0} complete, ${c.failed || 0} failed, ${c.stale || 0} stale, ` +
    `${c.unassessed || 0} unassessed of ${data.total} (${data.mode.toUpperCase()} assessments; atlas field: complete 41-page corpus).`;

  const columns = [
    { key: "destination_id", label: "destination" },
    { key: "status", label: "status", className: "status-cell" },
    ...data.dimensions.map((d) => ({ key: d, label: d, score: true })),
    { key: "is_authored_neighbor", label: "neighbor" },
  ];
  const valueOf = (row, col) => (col.score ? row.scores[col.key] : row[col.key]);

  const head = document.createElement("tr");
  for (const col of columns) {
    const th = textNode("th", col.label + (App.atlasSort.column === col.key ? (App.atlasSort.direction > 0 ? " ▲" : " ▼") : ""), col.className);
    th.addEventListener("click", () => {
      App.atlasSort = { column: col.key, direction: App.atlasSort.column === col.key ? -App.atlasSort.direction : (col.score ? -1 : 1) };
      renderAtlas();
    });
    head.appendChild(th);
  }
  table.appendChild(head);

  const sortCol = columns.find((col) => col.key === App.atlasSort.column) || columns[0];
  const rows = [...data.rows].sort((a, b) => {
    const va = valueOf(a, sortCol), vb = valueOf(b, sortCol);
    const aMissing = va === null || va === undefined, bMissing = vb === null || vb === undefined;
    if (aMissing || bMissing) return aMissing === bMissing ? 0 : (aMissing ? 1 : -1); // unassessed always last
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * App.atlasSort.direction;
    return String(va).localeCompare(String(vb), undefined, { numeric: true }) * App.atlasSort.direction;
  });
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const col of columns) {
      const value = valueOf(row, col);
      let text;
      let className = col.className || "";
      if (col.score) {
        const missing = value === null || value === undefined;
        text = missing ? "—" : String(Math.round(value * 100) / 100); // not assessed is never shown as 0
        if (missing) className = "unassessed";
      } else if (col.key === "is_authored_neighbor") {
        text = value ? (row.neighbor_relation || "yes") : "";
      } else {
        text = String(value);
      }
      tr.appendChild(textNode("td", text, className));
    }
    table.appendChild(tr);
  }
}

// --- preserve + optional note (unchanged capabilities) ---

async function onPreserve() {
  if (!App.currentBond || !App.currentBond.bond_id) return;
  el("preserve-btn").disabled = true;
  try {
    const outcome = await postJson("/api/preserve", { bond_id: App.currentBond.bond_id });
    el("preserve-status").textContent = `Preserved (vault entry ${outcome.entry_id}). Repeat-safe: clicking again returns the same entry.`;
  } catch (e) {
    el("preserve-status").textContent = `Preserve failed: ${e.message}`;
  } finally {
    el("preserve-btn").disabled = false;
  }
}

async function onSaveNote() {
  if (!App.followedRun || !App.followedRun.run_dir) return;
  const grounding = el("note-grounding").value;
  const effect = el("note-effect").value;
  try {
    await postJson("/api/review", {
      run_dir: App.followedRun.run_dir,
      correspondence: el("note-correspondence").value || null,
      reading_effect: el("note-change").value || null,
      grounding_score: grounding === "" ? null : parseInt(grounding, 10),
      effect_score: effect === "" ? null : parseInt(effect, 10),
      decision: el("note-decision").value || null,
    });
    el("note-status").textContent = "Saved.";
  } catch (e) {
    el("note-status").textContent = `Save failed: ${e.message}`;
  }
}

function renderTraversalHistory(readerState) {
  el("traversal-history").textContent = JSON.stringify(readerState, null, 2);
}

init().catch((e) => {
  const p = document.createElement("p");
  p.style.color = "red";
  p.textContent = `Failed to load reader: ${e.message}`;
  document.body.prepend(p);
});
