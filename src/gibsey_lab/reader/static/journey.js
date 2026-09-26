"use strict";

// Journey inspection: read-only. This file makes exactly two kinds of request, both GETs:
// /api/core/journey?session_id=... and /api/build. It never POSTs. Corpus text is only
// ever placed with textContent.

const EVIDENCE_NOTE = "decision evidence (model distribution) — no textual evidence span recorded";
const SESSION_STORAGE_KEY = "gibsey.coreSessionId"; // the reader keeps its session id here

const el = (id) => document.getElementById(id);

function textNode(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function renderPassage(container, text) {
  container.replaceChildren();
  const paragraphs = String(text || "").split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  for (const p of paragraphs) container.appendChild(textNode("p", p));
}

async function getJson(path) {
  const res = await fetch(path, { method: "GET" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || `HTTP ${res.status}`);
    error.data = data;
    error.status = res.status;
    throw error;
  }
  return data;
}

function requestedSessionId() {
  const fromQuery = new URLSearchParams(window.location.search).get("session_id");
  if (fromQuery) return fromQuery;
  try { return window.localStorage.getItem(SESSION_STORAGE_KEY) || ""; } catch (e) { return ""; }
}

function num(value, digits = 2) {
  return typeof value === "number" ? String(Math.round(value * 10 ** digits) / 10 ** digits) : "—";
}

function fitText(fit) {
  if (!fit) return "fit: not recorded";
  const score = typeof fit.score === "number" ? `${num(fit.score)} of 3` : "no score";
  const conf = typeof fit.confidence === "number" ? `, confidence ${num(fit.confidence)}` : "";
  return `${fit.dimension || "fit"}: ${score}${conf}`;
}

function headerItem(label, value, testid) {
  const wrap = document.createElement("div");
  wrap.appendChild(textNode("dt", `${label} `));
  const dd = textNode("dd", value === null || value === undefined ? "—" : String(value));
  if (testid) dd.dataset.testid = testid;
  wrap.appendChild(dd);
  return wrap;
}

function renderHeader(journey, build) {
  const header = el("journey-header");
  header.replaceChildren();
  header.hidden = false;
  header.dataset.sessionId = journey.session_id;
  header.dataset.revision = String(journey.revision);
  header.dataset.encounters = String(journey.encounter_count);
  header.dataset.paused = journey.paused ? "true" : "false";
  header.appendChild(headerItem("session", journey.session_id, "journey-session-id"));
  header.appendChild(headerItem("field", journey.field, "journey-field"));
  const score = journey.score || {};
  header.appendChild(headerItem("performance", score.score_id ? `${score.score_id} v${score.score_version} · ${score.movement} · ${score.status}` : "Historical neutral journey", "journey-score"));
  header.appendChild(headerItem("atlas config", (journey.atlas_config_ids || []).join(", ") || "none resolved yet", "journey-atlas-config"));
  header.appendChild(headerItem("revision", journey.revision, "journey-revision"));
  header.appendChild(headerItem("paused", journey.paused ? "yes" : "no", "journey-paused"));
  header.appendChild(headerItem("encounters", journey.encounter_count, "journey-encounter-count"));
  header.appendChild(headerItem("events", journey.event_count));
  header.appendChild(headerItem("started", journey.started_at));
  if (build) {
    header.appendChild(headerItem("build", `${(build.git_revision || "unknown").slice(0, 10)}${build.dirty ? " (uncommitted changes)" : ""}`, "journey-build"));
  }
}

function stateRow(label, before, after, key) {
  const cells = [textNode("span", label, "head"), textNode("span", before === undefined ? "" : String(before)), textNode("span", after === undefined ? "" : String(after))];
  if (key) cells[1].dataset.testid = `before-${key}`;
  if (key) cells[2].dataset.testid = `after-${key}`;
  return cells;
}

function renderStateGrid(action) {
  const grid = document.createElement("div");
  grid.className = "state-grid";
  grid.dataset.testid = "state-grid";
  const b = action.state_before || {};
  const a = action.state_after || {};
  for (const cell of stateRow("", "before", "after")) grid.appendChild(cell);
  for (const cell of stateRow("revision", b.revision, a.revision, "revision")) grid.appendChild(cell);
  for (const cell of stateRow("encounter count", b.encounter_count, a.encounter_count, "encounters")) grid.appendChild(cell);
  for (const cell of stateRow("count for this version", b.count_for_version, a.count_for_version, "count-for-version")) grid.appendChild(cell);
  for (const cell of stateRow("active version", b.active_version, a.active_version, "active-version")) grid.appendChild(cell);
  return grid;
}

function renderBond(bond, position) {
  const item = document.createElement("details");
  item.className = bond.selected ? "bond selected" : "bond";
  item.dataset.testid = "journey-bond";
  item.dataset.bondVersionId = bond.bond_version_id || "";
  item.dataset.selected = bond.selected ? "true" : "false";
  if (bond.selected) item.open = true;
  const summary = document.createElement("summary");
  summary.appendChild(textNode("span", `${position}. `, "option-rank"));
  summary.appendChild(textNode("span", bond.destination_page || "?", "page-tag"));
  summary.appendChild(textNode("span", ` ${bond.destination_version || ""}`, "bond-meta"));
  const tier = bond.tier_label || (bond.tier === "supported" ? "Supported" : "Exploratory — weak or uncertain fit");
  summary.appendChild(textNode("span", tier, `tier-badge tier-${bond.tier === "supported" ? "supported" : "exploratory"}`));
  if (bond.selected) summary.appendChild(textNode("span", "selected", "selected-mark"));
  item.appendChild(summary);

  const body = document.createElement("div");
  if (bond.wording) {
    const wording = textNode("blockquote", `Offered: «${bond.wording}»`, "bond-wording");
    wording.dataset.testid = "journey-bond-wording";
    body.appendChild(wording);
  }
  body.appendChild(textNode("div", `${fitText(bond.operator_fit)}${bond.operator_fit && bond.operator_fit.nearest_level !== undefined && bond.operator_fit.nearest_level !== null ? ` (nearest level ${bond.operator_fit.nearest_level})` : ""}`, "option-fit"));
  body.appendChild(textNode("span", bond.evidence_note || EVIDENCE_NOTE, "evidence-note"));
  const cautions = (bond.cautions || []).join(", ");
  if (cautions) body.appendChild(textNode("div", `cautions: ${cautions}`, "bond-meta"));
  body.appendChild(textNode("div", `bond version: ${bond.bond_version_id || "—"}`, "bond-meta"));
  body.appendChild(textNode("div", `assessment id: ${bond.assessment_id || "none recorded"}`, "bond-meta"));
  body.appendChild(textNode("div", `wording source: ${bond.wording_source || "—"} · rank ${bond.rank === undefined ? "—" : bond.rank}`, "bond-meta"));
  item.appendChild(body);
  return item;
}

function renderOfferSet(action) {
  const details = document.createElement("details");
  details.className = "offer-details";
  details.dataset.testid = "journey-offer-set";
  const offer = action.offer_set;
  if (!offer) {
    details.appendChild(textNode("summary", "Offer set: not found in this journal"));
    details.appendChild(textNode("p", "The committed action names an offer set this journal does not contain; nothing is reconstructed in its place.", "missing"));
    return details;
  }
  const bonds = offer.bonds || [];
  details.appendChild(textNode("summary", `Offer set ${offer.offer_set_id} — ${offer.operator} under ${offer.policy} at revision ${offer.revision}: ${bonds.length} bond${bonds.length === 1 ? "" : "s"} in the order offered`));
  const meta = document.createElement("div");
  meta.className = "bond-meta";
  meta.appendChild(textNode("div", `source ${offer.source_version} · atlas config ${offer.atlas_config_id || "—"} · options policy ${offer.options_policy_version || "—"} · options state ${offer.options_state || "—"} · resolved at ${offer.at || "—"} (event ${offer.event_seq})`));
  const counts = offer.counts || {};
  const exclusions = offer.exclusions || {};
  meta.appendChild(textNode("div", `counts: eligible ${counts.eligible ?? "—"}, usable ${counts.usable ?? "—"}, supported ${counts.supported ?? "—"}, shown ${bonds.length} · excluded by policy ${exclusions.ineligible_policy ?? "—"}, unusable ${exclusions.unusable ?? "—"}`));
  details.appendChild(meta);
  details.appendChild(textNode("span", action.evidence_note || EVIDENCE_NOTE, "evidence-note"));
  bonds.forEach((bond, index) => details.appendChild(renderBond(bond, index + 1)));
  return details;
}

function renderEncounter(encounter) {
  const item = document.createElement("details");
  item.className = "encounter";
  item.dataset.testid = "journey-encounter";
  item.dataset.index = String(encounter.encounter_index);
  item.dataset.versionId = encounter.version_id || "";
  item.dataset.pageId = encounter.page_id || "";
  item.dataset.via = encounter.via || "";
  item.dataset.kind = encounter.kind_id || "";
  item.dataset.cause = encounter.cause || "";
  const summary = document.createElement("summary");
  summary.appendChild(textNode("span", `#${encounter.encounter_index} `, "option-rank"));
  summary.appendChild(textNode("span", encounter.page_id || "?", "page-tag"));
  summary.appendChild(textNode("span", encounter.version_id || "", "bond-meta"));
  // The encounter's provenance, as labeled by the server: initial entry / literary bond
  // selected / manual relocation — <cause>. A relocation never shows an offer set.
  const kindId = encounter.kind_id || (encounter.via === "Q" ? "bond" : (encounter.via === "manual" ? "relocation" : "start"));
  const kindText = encounter.kind || (kindId === "bond" ? "literary bond selected" : (kindId === "relocation" ? `manual relocation — ${encounter.cause || "other"}` : "initial entry"));
  const kind = textNode("span", kindText, `via-badge via-${kindId === "bond" ? "q" : (kindId === "relocation" ? "manual" : "start")}`);
  kind.dataset.testid = "encounter-kind";
  kind.dataset.kind = kindId;
  kind.dataset.cause = encounter.cause || "";
  summary.appendChild(kind);
  if (encounter.is_return) {
    const marker = textNode("span", `return to an earlier version: distance ${encounter.return_index_distance}, ${encounter.intervening_encounters} intervening`, "return-badge");
    marker.dataset.testid = "encounter-return";
    marker.dataset.distance = String(encounter.return_index_distance);
    marker.dataset.intervening = String(encounter.intervening_encounters);
    summary.appendChild(marker);
  }
  if (encounter.prose && encounter.prose.title) summary.appendChild(textNode("span", `  ${encounter.prose.title}`, "offer-title"));
  item.appendChild(summary);

  const body = document.createElement("div");
  body.className = "encounter-body";
  if (encounter.score_after && encounter.score_after.score_id) {
    const score = encounter.score_after;
    body.appendChild(textNode("p", `Performance after arrival: ${score.movement} · ${score.counter || 0} moves in this movement · ${score.status}`, "bond-meta"));
  }
  body.appendChild(textNode("div", `arrived at ${encounter.at || "—"} (journal event ${encounter.event_seq}; wall time as recorded, not synthetic) · revision after ${encounter.revision_after} · encounters so far ${encounter.encounter_count_after} · this version seen ${encounter.count_for_version_after} time${encounter.count_for_version_after === 1 ? "" : "s"}`, "bond-meta"));
  if (encounter.is_return) {
    body.appendChild(textNode("div", encounter.return_marker || `earlier encounter of this exact version: #${encounter.previous_encounter_index}; index distance ${encounter.return_index_distance}; intervening encounters ${encounter.intervening_encounters}`, "bond-meta"));
  }

  const prose = document.createElement("details");
  prose.className = "prose-details";
  prose.dataset.testid = "journey-prose";
  prose.open = encounter.encounter_index === 0;
  const p = encounter.prose || {};
  if (typeof p.text === "string") {
    prose.appendChild(textNode("summary", `Exact prose of ${encounter.version_id} (sha256 ${(p.sha256 || "").slice(0, 12)}…)`));
    const passage = document.createElement("div");
    passage.className = "passage";
    passage.dataset.testid = "journey-prose-text";
    renderPassage(passage, p.text);
    prose.appendChild(passage);
  } else {
    prose.open = true;
    prose.appendChild(textNode("summary", `Exact prose of ${encounter.version_id}: not shown`));
    const note = textNode("p", p.note || "This version is no longer current; nothing is shown in its place.", "missing");
    note.dataset.testid = "journey-prose-missing";
    prose.appendChild(note);
  }
  body.appendChild(prose);

  if (encounter.action) {
    const action = encounter.action;
    const selection = document.createElement("div");
    selection.dataset.testid = "journey-selection";
    selection.appendChild(textNode("h3", "Selection"));
    selection.appendChild(textNode("div", `request id ${action.request_id} · bond version ${action.bond_version_id} · ${action.operator} · expected revision ${action.expected_revision}`, "bond-meta"));
    if (action.wording) {
      const wording = textNode("blockquote", `Offered: «${action.wording}»`, "bond-wording");
      wording.dataset.testid = "journey-selected-wording";
      selection.appendChild(wording);
    }
    selection.appendChild(textNode("div", `${action.tier === "supported" ? "Supported" : "Exploratory"} · ${fitText(action.operator_fit)} · assessment id ${action.assessment_id || "none recorded"}`, "option-fit"));
    selection.appendChild(textNode("span", action.evidence_note || EVIDENCE_NOTE, "evidence-note"));
    body.appendChild(selection);
    body.appendChild(textNode("h3", "State before → after"));
    body.appendChild(renderStateGrid(action));
    body.appendChild(renderOfferSet(action));
  } else if (encounter.relocation) {
    const move = encounter.relocation;
    const block = document.createElement("div");
    block.dataset.testid = "journey-relocation";
    block.dataset.cause = move.cause || "";
    block.appendChild(textNode("h3", `Manual relocation — ${move.cause || "other"}`));
    block.appendChild(textNode("p", `No bond, no operator, no offer set: ${move.note || "a manual relocation asserts no literary relationship"}.`, "hint"));
    block.appendChild(textNode("div", `from ${move.from_page || "?"} (${move.from_version || "?"}) to ${move.to_page || encounter.page_id} (${move.to_version || encounter.version_id}) · request id ${move.request_id} · expected revision ${move.expected_revision}`, "bond-meta"));
    body.appendChild(block);
    body.appendChild(textNode("h3", "State before → after"));
    body.appendChild(renderStateGrid(move));
  } else {
    body.appendChild(textNode("p", "Initial entry: the journey started here. No offer set, no selection, no transition.", "hint"));
  }
  item.appendChild(body);
  return item;
}

function renderRejections(journey) {
  const panel = el("rejections-panel");
  const list = el("rejections");
  list.replaceChildren();
  const rejections = journey.rejections || [];
  el("rejections-count").textContent = String(rejections.length);
  panel.hidden = rejections.length === 0;
  for (const r of rejections) {
    const what = r.kind === "relocation" ? `relocation to ${r.relocate_to || "?"} (${r.cause || "?"})` : "follow";
    list.appendChild(textNode("li", `event ${r.seq} at ${r.at}: ${what} refused — ${r.code}: ${r.reason} (request ${r.request_id}, expected revision ${r.expected_revision}, session was at ${r.revision_at_rejection})`));
  }
}

function renderScoreInspection(journey) {
  const panel = el("score-inspection");
  panel.replaceChildren();
  panel.hidden = !journey.score || !journey.score.score_id;
  if (panel.hidden) return;
  panel.appendChild(textNode("h2", journey.synthetic ? "Synthetic performance and choice rules" : "Performance and choice rules"));
  const config = document.createElement("details");
  config.appendChild(textNode("summary", "Pinned score configuration and lifecycle"));
  config.appendChild(textNode("pre", JSON.stringify({ score: journey.score, lifecycle_events: journey.lifecycle_events }, null, 2)));
  panel.appendChild(config);
  for (const offer of journey.offer_sets || []) {
    const details = document.createElement("details");
    details.dataset.testid = "journey-score-decisions";
    details.appendChild(textNode("summary", `${offer.source_page} · ${offer.operator} · revision ${offer.revision}: ${(offer.bonds || []).length} available choices`));
    for (const decision of offer.decisions || []) {
      details.appendChild(textNode("p", `${decision.destination_page || decision.candidate_id} — ${decision.allowed ? "rule passed" : "excluded by rule"}: ${decision.reason || decision.code} (${decision.rule_id})`));
      details.appendChild(textNode("pre", JSON.stringify(decision, null, 2)));
    }
    panel.appendChild(details);
  }
}

async function load(sessionId) {
  const status = el("load-status");
  const container = el("encounters");
  container.replaceChildren();
  el("journey-header").hidden = true;
  el("rejections-panel").hidden = true;
  el("raw-panel").hidden = true;
  if (!sessionId) {
    status.className = "status-line state-info";
    status.textContent = "No session id: pass ?session_id=… or open this page from the reader (it uses the reader's stored session).";
    return;
  }
  status.className = "status-line status-loading";
  status.textContent = "Reading the journal…";
  let journey;
  try {
    journey = await getJson(`/api/core/journey?session_id=${encodeURIComponent(sessionId)}`);
  } catch (e) {
    status.className = "status-line state-error";
    status.textContent = `Could not read this journey: ${e.message}`;
    return;
  }
  let build = null;
  try { build = await getJson("/api/build"); } catch (e) { /* informational */ }
  renderHeader(journey, build);
  renderScoreInspection(journey);
  status.className = "status-line state-selected";
  status.textContent = `${journey.encounter_count} encounter${journey.encounter_count === 1 ? "" : "s"} from ${journey.event_count} journal events; nothing was written by this page.`;
  for (const encounter of journey.encounters || []) container.appendChild(renderEncounter(encounter));
  renderRejections(journey);
  el("raw-panel").hidden = false;
  el("raw-body").textContent = JSON.stringify(journey, null, 2);
  if (build) {
    el("build-id").textContent = `build ${(build.git_revision || "unknown").slice(0, 10)}${build.dirty ? " (uncommitted changes)" : ""} · server started ${build.server_started_at}`;
  }
  const url = new URL(window.location.href);
  if (url.searchParams.get("session_id") !== sessionId) {
    url.searchParams.set("session_id", sessionId);
    window.history.replaceState(null, "", url.toString());
  }
}

// Keyboard: with an encounter's summary focused, ArrowDown/ArrowUp move to the next/previous encounter.
document.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const active = document.activeElement;
  if (!active || active.tagName !== "SUMMARY" || !active.parentElement.classList.contains("encounter")) return;
  const summaries = [...document.querySelectorAll(".encounter > summary")];
  const index = summaries.indexOf(active);
  const next = summaries[index + (event.key === "ArrowDown" ? 1 : -1)];
  if (next) { next.focus(); event.preventDefault(); }
});

el("session-form").addEventListener("submit", (event) => {
  event.preventDefault();
  load(el("session-input").value.trim());
});

const initial = requestedSessionId();
el("session-input").value = initial;
load(initial);
