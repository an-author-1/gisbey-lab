"use strict";

// Outcome states (exact ids, shared with reader/outcomes.py):
//   operator: not_requested | loading | selected | abstained | no_candidates | error
//   offers:   not_requested | loading | offers | no_qualified | no_candidates | atlas_incomplete | error
//
// Rules this file keeps:
// - An operator button shows ranked destinations from the saved atlas (POST
//   /api/core/options: the Core's persisted offer set at the session's current revision --
//   no provider work, no session-log write, never an empty unexplained panel), and
//   exploratory (weak-fit) options preview and follow exactly like supported ones.
// - Follow is POST /api/core/execute with the revision the offer set was made at and a
//   fresh request_id per click (the same id again only when that click got no response).
//   A stale revision is a refusal that moves nothing: the current revision is shown and
//   the options are re-resolved. A paused session says so.
// - The Core session id lives in localStorage; on load the session is resumed (a reload,
//   a second tab, a direct URL, coming back from /journey: GET, no event). A stored id the
//   server does not know is not adopted: the server mints a fresh one and says so.
// - Every manual move (Previous, Next, the page list, in-app Back, browser Back/Forward,
//   the conflict "Go to" / "Continue here") is POST /api/core/relocate in the SAME session:
//   one event, one encounter, no bond, no operator, no offer set. Each click sends a fresh
//   request_id (reused only when the same click got no response) and the revision of the
//   current session view; nothing moves on screen before the Core answers, and what is
//   rendered is the page the Core committed, never the page that was asked for. A stale
//   revision re-syncs the session view and shows the authoritative page with a note; a
//   move to the already-active version is a no-op (rendered, not recorded).
// - Browser history: one pushState({session_id, encounter_index}) after every committed
//   arrival (start, follow, relocation). popstate never pushes: it relocates with cause
//   history_back / history_forward (decided by comparing the popped encounter index with
//   the entry the tab was on) to the page of that encounter's version. A reload or a
//   bfcache restore (pageshow) is a resume, so no navigation is ever recorded twice.
// - A fresh journey is explicit: "Start a new journey" (confirmed in-page, never a
//   browser dialog) or a field change -> POST /api/core/session {page, new: true}.
// - The client no longer logs page_viewed for any move that goes through the Core; the
//   projector's mirror line is the only session-log line for it. `via=reload` stays as a
//   legacy client line on a resume (it creates no encounter anywhere).
// - The old /api/operator-options and /api/follow-option endpoints are no longer used by
//   the buttons (the explicit Refine action still reads the legacy option set it needs).
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
  session: null,         // Core session view: {session_id, revision, active_page, paused, encounter_count, encounters, field, last_arrival}
  sessionReady: Promise.resolve(),
  sessionError: null,
  sessionNote: "",       // e.g. "a stored journey id was unknown; a new journey started"
  executeAttempts: {},   // "offer_set|bond" -> request_id of a click whose response was lost (reused on retry)
  relocateAttempts: {},  // "session|page|cause|revision" -> request_id of a move whose response was lost (reused on retry)
  relocation: null,      // {key, promise} while one relocation is outstanding; an identical click joins it
  historyPosition: null, // encounter_index carried by the browser-history entry this tab is on
  loadType: null,        // navigate | reload | back_forward (performance navigation type of this load)
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
  if (isDemo()) return Promise.resolve();
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

// --- the Core session: one journey of committed follows, resumed on load ---

const SESSION_STORAGE_KEY = "gibsey.coreSessionId";
const PRIOR_SESSION_KEY = "gibsey.preDemoSessionId";

function isDemo() {
  return !!(App.session && App.session.synthetic);
}

async function adoptSessionField(session) {
  App.field = session.field;
  const select = el("field-select");
  if (![...select.options].some((option) => option.value === App.field)) {
    const option = document.createElement("option");
    option.value = App.field;
    option.textContent = "Synthetic recurrence demonstration";
    select.appendChild(option);
  }
  select.value = App.field;
  await loadPageList();
  await checkFieldStatus();
}

async function startDemo(mode) {
  try {
    const previous = App.session && App.session.session_id;
    const session = await postJson("/api/core/demo", { mode, session_id: previous });
    if (previous) localStorage.setItem(PRIOR_SESSION_KEY, previous);
    applySession(session);
    await adoptSessionField(session);
    App.viewHistory = [];
    saveViewHistory();
    await showPage(session.active_page);
    recordArrival(session.encounter_count - 1);
    await selectOperator("ECHO");
    el("score-demo-status").textContent = "Synthetic material only. Choose Follow, then choose an operator on each arrival.";
  } catch (error) {
    el("score-demo-status").textContent = error.message;
  }
}

async function scoreLifecycle(action, resumeSessionId) {
  const session = App.session;
  const view = await postJson("/api/core/lifecycle", {
    session_id: session.session_id, action, expected_revision: session.revision, request_id: newRequestId(),
    resume_session_id: resumeSessionId || undefined,
  });
  applySession(view);
  return view;
}

async function leaveDemo() {
  try {
    const demonstration = App.session.session_id;
    const previous = localStorage.getItem(PRIOR_SESSION_KEY);
    await scoreLifecycle("exit", previous);
    const session = await postJson("/api/core/session", { session_id: previous || undefined });
    applySession(session);
    await adoptSessionField(session);
    localStorage.removeItem(PRIOR_SESSION_KEY);
    App.viewHistory = [];
    saveViewHistory();
    await showPage(session.active_page);
    syncHistoryEntry(session.encounter_count - 1);
    const status = el("score-demo-status");
    status.textContent = "Your literary journey is restored. ";
    const link = textNode("a", "Inspect the demonstration you just left");
    link.href = `/journey?session_id=${encodeURIComponent(demonstration)}`;
    status.appendChild(link);
  } catch (error) {
    el("score-demo-status").textContent = error.message;
  }
}

function renderScore() {
  const demo = isDemo();
  const score = (App.session && App.session.score) || {};
  el("start-neutral-demo").disabled = demo;
  el("start-recurrence-demo").disabled = demo;
  el("leave-demo").hidden = !demo;
  el("field-select").disabled = demo;
  el("offers-panel").hidden = demo;
  el("atlas-panel").hidden = demo;
  el("history-panel").hidden = demo;
  el("mode-panel").hidden = demo;
  const progress = el("score-progress");
  progress.dataset.movement = score.movement || "";
  progress.dataset.status = score.status || "";
  progress.dataset.counter = String(score.counter || 0);
  if (!demo) {
    progress.textContent = "";
    return;
  }
  const movement = ((score.config || {}).movements || {})[score.movement] || {};
  const completed = score.status === "complete";
  const status = { complete: "Complete — you returned to the starting passage.", ended_by_reader: "Ended by you before completion.", exited: "You left this demonstration.", blocked: "No choice satisfies this part of the demonstration." }[score.status];
  const neutral = score.score_id === "neutral";
  const label = neutral ? "Neutral choices" : (score.movement === "outward" ? "Outward — visit two new passages" : "Return — come back to the starting passage");
  progress.textContent = `${App.session.paused ? "Paused. " : ""}${status || label}${!status && movement.advance_after ? ` · ${score.counter || 0} of ${movement.advance_after} moves` : ""}${completed ? " You may leave or inspect the journey." : ""}`;
  if (!neutral && !status) progress.appendChild(textNode("span", " Manual navigation is unavailable here; use the offered choices or Leave demonstration."));
  if (score.status === "active" || score.status === "blocked") {
    const end = textNode("button", "End this performance", "session-toggle");
    end.dataset.testid = "score-end";
    end.addEventListener("click", async () => {
      try { await scoreLifecycle("end_journey"); } catch (error) { el("score-demo-status").textContent = error.message; }
    });
    progress.appendChild(end);
  }
}

function readStoredSessionId() {
  try { return window.localStorage.getItem(SESSION_STORAGE_KEY) || null; } catch (e) { return null; }
}

function storeSessionId(sessionId) {
  try {
    if (sessionId) window.localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
    else window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch (e) { /* a fresh session is started next time instead */ }
}

function applySession(view) {
  App.session = view;
  App.sessionError = null;
  storeSessionId(view.session_id);
  renderSessionLine();
  renderScore();
}

async function resumeOrStartSession(fallbackPage, options) {
  // On load: resume the stored session (GET-equivalent: no event). An absent or unknown
  // id starts a new journey at the reader's last recorded page with a SERVER-minted id
  // (an unknown stored id is never adopted). `{new: true}` is the explicit fresh journey.
  const stored = readStoredSessionId();
  const fresh = !!(options && options.new);
  try {
    const view = await postJson("/api/core/session", {
      session_id: stored || undefined, page: fallbackPage || undefined, field: App.field, new: fresh || undefined,
    });
    App.sessionNote = view.reason === "unknown_session"
      ? `the stored journey id ${view.previous_session_id || ""} was unknown to the server, so a new journey started here`
      : (view.reason === "new_journey" ? "a new journey started here" : "");
    applySession(view);
  } catch (e) {
    App.session = null;
    App.sessionError = e.message;
    renderSessionLine();
  }
  return App.session;
}

async function startNewJourney(pageId) {
  // Explicit fresh journey at `pageId` (the "Start a new journey" control, a field change).
  // The earlier journey stays recorded; this tab's browser history from it stays too, but
  // its entries belong to that session and are only ever resumed, never relocated into.
  const session = await resumeOrStartSession(pageId, { new: true });
  if (!session) return null;
  App.viewHistory = [];
  saveViewHistory();
  el("back-btn").disabled = true;
  await showPage(session.active_page);
  recordArrival(session.encounter_count - 1);
  setMoveStatus("", "");
  return session;
}

// --- relocation: every manual move is one committed Core event in the same session ---

function setMoveStatus(text, kind) {
  const line = el("move-status");
  line.textContent = text || "";
  line.className = `status-line ${kind === "error" ? "state-error" : (kind ? "state-info" : "")}`;
  line.dataset.state = text ? (kind || "info") : "";
  line.hidden = !text;
}

async function relocate(pageId, cause, options) {
  // POST /api/core/relocate and render what the Core committed. `options.fromHistory` is
  // set by the popstate handler, which never pushes a history entry. Returns the outcome
  // (`noop: true` when the session was already at that exact version), or null when
  // nothing moved (a refusal, or no response).
  if (!pageId) return null;
  const fromHistory = !!(options && options.fromHistory);
  if (!App.session) {
    await resumeOrStartSession(App.source || pageId); // a lost session is re-resumed (or started) before the move
    if (!App.session) {
      setMoveStatus(`Not moved to ${pageId}: there is no Core session (${App.sessionError || "unknown error"}). Try again.`, "error");
      return null;
    }
  }
  const session = App.session;
  const key = [session.session_id, pageId, cause, session.revision].join("|");
  if (App.relocation && App.relocation.key === key) return App.relocation.promise; // the same click again before the answer: one move
  // One request_id per click; reused only when that click got NO response, so a retry is
  // the same move and the Core answers with its recorded result instead of a second one.
  const requestId = App.relocateAttempts[key] || newRequestId();
  App.relocateAttempts[key] = requestId;
  const previous = App.source;
  const promise = (async () => {
    let outcome = null;
    let error = null;
    try {
      outcome = await postJson("/api/core/relocate", {
        session_id: session.session_id, page: pageId, expected_revision: session.revision, request_id: requestId, cause,
      });
    } catch (e) {
      error = e;
    }
    if (!error || error.status !== undefined) delete App.relocateAttempts[key]; // answered: the next click is a new move

    if (outcome) {
      if (outcome.session) applySession(outcome.session);
      if (!outcome.noop && cause !== "back" && previous && previous !== outcome.to_page) {
        App.viewHistory.push(previous); // the in-app Back stack (per tab); nothing server-side
        saveViewHistory();
      }
      await showPage(outcome.to_page); // the committed page, never the requested one
      if (outcome.noop) {
        setMoveStatus(`Already at ${outcome.to_page} (${outcome.to_version}): rendering it again is not a new encounter.`, "info");
      } else {
        setMoveStatus("", "");
        if (!fromHistory) recordArrival(outcome.encounter_index);
        if (outcome.duplicate) setMoveStatus(`This move was already recorded (encounter #${outcome.encounter_index}); nothing moved twice.`, "info");
      }
      return outcome;
    }

    const refusal = error.data || {};
    if (refusal.session) applySession(refusal.session);
    if (refusal.code === "stale_revision") {
      // Another tab or window moved this journey on. Re-sync and show where it actually is.
      const current = refusal.session || await refreshSession();
      if (current) {
        await showPage(current.active_page);
        syncHistoryEntry(current.encounter_count - 1);
        setMoveStatus(`Not moved to ${pageId}: this tab expected revision ${session.revision}, but the journey is at revision ${current.revision} ` +
          `(another tab or window moved it to ${current.active_page}). Showing ${current.active_page}, where the journey actually is; choose the move again from here.`, "error");
      } else {
        setMoveStatus(`Not moved to ${pageId}: the journey moved on (revision ${refusal.current_revision}) and could not be re-read. Reload to resume it.`, "error");
      }
      return null;
    }
    if (refusal.code === "paused") {
      setMoveStatus(`Not moved to ${pageId}: the session is paused. Resume it (above) to keep navigating.`, "error");
      return null;
    }
    if (error.status === undefined) {
      setMoveStatus(`Not moved to ${pageId}: no response arrived. The same move again retries with the same request id, so it is recorded at most once.`, "error");
      return null;
    }
    setMoveStatus(`Not moved to ${pageId}: ${refusal.reason || error.message}`, "error");
    return null;
  })();
  App.relocation = { key, promise };
  try {
    return await promise;
  } finally {
    if (App.relocation && App.relocation.promise === promise) App.relocation = null;
  }
}

// --- browser history: one entry per committed arrival; popstate relocates, never pushes ---

function historyState(encounterIndex) {
  return { session_id: App.session ? App.session.session_id : null, encounter_index: encounterIndex };
}

function recordArrival(encounterIndex) {
  // Called by the click and follow paths after the Core committed an arrival. Never by
  // popstate. The guard makes a duplicate answer (same encounter) a single entry.
  if (typeof encounterIndex !== "number" || !App.session) return;
  if (App.historyPosition === encounterIndex && window.history.state && window.history.state.session_id === App.session.session_id) return;
  window.history.pushState(historyState(encounterIndex), "", window.location.href);
  App.historyPosition = encounterIndex;
}

function syncHistoryEntry(encounterIndex) {
  // A resume (load, reload, pageshow, re-sync after a stale revision) labels the CURRENT
  // entry with where the journey is; it adds no entry.
  if (typeof encounterIndex !== "number" || !App.session) return;
  window.history.replaceState(historyState(encounterIndex), "", window.location.href);
  App.historyPosition = encounterIndex;
}

async function resumeHere(note) {
  // Render the journey's committed position without any event (reload, pageshow, an
  // entry from another journey): GET the session view, show its active page.
  const session = App.session ? await refreshSession() : await resumeOrStartSession(App.source);
  if (!session) return;
  await showPage(session.active_page);
  syncHistoryEntry(session.encounter_count - 1);
  if (note) setMoveStatus(note, "info");
}

async function onPopState(event) {
  const state = event.state;
  if (!state || typeof state.encounter_index !== "number") return; // not one of this app's entries
  if (!App.session || state.session_id !== App.session.session_id) {
    await resumeHere(`That history entry belongs to another journey (${state.session_id || "unknown"}); this one is shown where it is.`);
    return;
  }
  const from = App.historyPosition;
  const cause = typeof from === "number" && state.encounter_index < from ? "history_back" : "history_forward";
  App.historyPosition = state.encounter_index;
  const target = (App.session.encounters || [])[state.encounter_index];
  if (!target) {
    await resumeHere(`That history entry (#${state.encounter_index}) is not in this journey's encounters; the journey is shown where it is.`);
    return;
  }
  await relocate(target.page_id, cause, { fromHistory: true });
}

function onPageShow(event) {
  // A bfcache restore keeps this script's state but the journey may have moved on: resume.
  if (event.persisted) resumeHere("Restored from the browser cache: the journey was re-read, nothing was recorded.");
}

async function refreshSession() {
  if (!App.session) return null;
  try {
    applySession(await api(`/api/core/session?session_id=${encodeURIComponent(App.session.session_id)}`));
  } catch (e) {
    App.sessionError = e.message;
    renderSessionLine();
  }
  return App.session;
}

function renderSessionLine() {
  const line = el("core-session");
  const s = App.session;
  line.replaceChildren();
  line.dataset.sessionId = s ? s.session_id : "";
  line.dataset.revision = s ? String(s.revision) : "";
  line.dataset.encounters = s ? String(s.encounter_count) : "";
  line.dataset.paused = s && s.paused ? "true" : "false";
  if (!s) {
    line.textContent = App.sessionError ? `No Core session: ${App.sessionError}. Nothing can move or be followed until one starts; the next Previous, Next or page-list click tries to start one.` : "Starting a journey...";
    return;
  }
  line.appendChild(textNode("span", "Journey ", "session-label"));
  const link = document.createElement("a");
  link.href = `/journey?session_id=${encodeURIComponent(s.session_id)}`;
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = s.session_id;
  link.dataset.testid = "journey-link";
  line.appendChild(link);
  const n = s.encounter_count;
  line.appendChild(textNode("span", ` · revision ${s.revision} · ${n} encounter${n === 1 ? "" : "s"} · at ${s.active_page}${s.paused ? " · PAUSED" : ""}`));
  const arrival = s.last_arrival || {};
  const kind = arrival.kind || "";
  const arrivalText = kind === "manual" ? `manual (${arrival.cause || "other"})` : (kind === "bond" ? "literary bond" : (kind === "start" ? "initial entry" : kind));
  const arrivalEl = textNode("span", ` · arrived by ${arrivalText}${arrival.is_return ? " · a return" : ""}`, "arrival-kind");
  arrivalEl.dataset.testid = "last-arrival-kind";
  arrivalEl.dataset.kind = kind;
  arrivalEl.dataset.cause = arrival.cause || "";
  arrivalEl.dataset.encounterIndex = typeof arrival.encounter_index === "number" ? String(arrival.encounter_index) : "";
  line.appendChild(arrivalEl);
  const fresh = textNode("button", "Start a new journey", "session-toggle");
  fresh.dataset.testid = "new-journey";
  fresh.disabled = isDemo();
  fresh.addEventListener("click", () => showNewJourneyConfirm());
  line.appendChild(fresh);
  const toggle = textNode("button", s.paused ? "Resume session" : "Pause session", "session-toggle");
  toggle.dataset.testid = s.paused ? "session-resume" : "session-pause";
  toggle.disabled = ["complete", "ended_by_reader", "exited"].includes((s.score || {}).status);
  toggle.addEventListener("click", async () => {
    toggle.disabled = true;
    try {
      applySession(await postJson(s.paused ? "/api/core/resume" : "/api/core/pause", { session_id: s.session_id }));
      if (App.operator) { delete App.options[App.operator]; loadOptions(App.operator); }
    } catch (e) {
      App.sessionError = e.message;
      renderSessionLine();
    }
  });
  line.appendChild(toggle);
  if (App.sessionNote) {
    const note = textNode("span", ` (${App.sessionNote})`, "kind-note");
    note.dataset.testid = "session-note";
    line.appendChild(note);
  }
  if (s.position && s.position.agrees === false) {
    line.appendChild(textNode("span", ` (the session log last placed the reader on ${s.position.logged_page}; the Core session is the authority for follows)`, "kind-note"));
  }
}

function showNewJourneyConfirm() {
  // In-page confirmation (never window.confirm): the current journey stays recorded and
  // readable at its journey link; a new one starts at the page on screen.
  const box = el("new-journey-confirm");
  box.replaceChildren();
  box.hidden = false;
  const current = App.session ? App.session.session_id : "none";
  box.appendChild(textNode("p", `Start a new journey from ${App.source}? The current journey (${current}, ${App.session ? App.session.encounter_count : 0} encounter${App.session && App.session.encounter_count === 1 ? "" : "s"}) stays recorded and can still be inspected; nothing is deleted. The new journey begins with ${App.source} as its initial entry.`));
  const actions = document.createElement("div");
  actions.className = "action-row";
  const yes = textNode("button", "Yes, start a new journey here");
  yes.dataset.testid = "new-journey-confirm";
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    await startNewJourney(App.source);
    box.hidden = true;
    if (App.operator) { delete App.refine[App.operator]; delete App.options[App.operator]; }
    renderOptions();
    renderOffers();
    renderOperatorPanel();
    if (App.operator) loadOptions(App.operator);
  });
  const no = textNode("button", "Keep this journey");
  no.dataset.testid = "new-journey-cancel";
  no.addEventListener("click", () => { box.hidden = true; });
  actions.appendChild(yes);
  actions.appendChild(no);
  box.appendChild(actions);
  box.scrollIntoView({ block: "center" });
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
    // A field is another corpus: a new journey starts at its first page (explicitly `new`).
    const previousField = App.field;
    App.field = fieldSelect.value;
    App.navGeneration++;
    logNavigation("field_selected", { from_field: previousField });
    await checkFieldStatus();
    await loadPageList();
    const groups = el("page-select").querySelectorAll("optgroup");
    const firstPage = groups.length ? groups[0].querySelector("option").value : null;
    App.source = null;
    await startNewJourney(firstPage);
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
  // Every manual control is a relocation in the same journey, with its cause. The click
  // handlers never touch history themselves beyond recordArrival after the commit.
  el("back-btn").addEventListener("click", onBack);
  el("prev-btn").addEventListener("click", () => {
    if (App.currentPage && App.currentPage.previous_id) relocate(App.currentPage.previous_id, "previous");
  });
  el("next-btn").addEventListener("click", () => {
    if (App.currentPage && App.currentPage.next_id) relocate(App.currentPage.next_id, "next");
  });
  el("page-select").addEventListener("change", () => {
    const chosen = el("page-select").value;
    el("page-select").value = App.source || chosen; // the list shows the committed page until the Core answers
    relocate(chosen, "page_list");
  });
  window.addEventListener("popstate", onPopState);
  window.addEventListener("pageshow", onPageShow);
  el("follow-immediately-toggle").addEventListener("change", (e) => {
    App.followImmediately = e.target.checked;
  });
  el("start-neutral-demo").addEventListener("click", () => startDemo("neutral"));
  el("start-recurrence-demo").addEventListener("click", () => startDemo("recurrence"));
  el("leave-demo").addEventListener("click", leaveDemo);
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
  try {
    const nav = performance.getEntriesByType("navigation")[0];
    App.loadType = nav ? nav.type : null; // navigate | reload | back_forward: all of them resume
  } catch (e) { App.loadType = null; }

  // A fallback start page for a NEW journey only: the last page recorded in the session
  // log, else the recorded Q position, else the first page. Loading never asks Jev anything.
  const readerState = await api("/api/reader-state");
  const last = readerState.last_viewed;
  let start = null;
  if (last && last.page_id && (!last.field || last.field === App.field)) start = last.page_id;
  if (!start) start = readerState.active_passage || readerState.active_page;
  if (start && !el("page-select").querySelector(`option[value="${CSS.escape(start)}"]`)) start = null;
  if (!start) {
    const firstGroup = el("page-select").querySelector("optgroup");
    start = firstGroup ? firstGroup.querySelector("option").value : null;
  }
  // The Core session is resumed first (no event); where it is, the reader is. A stored
  // id the server does not know is replaced by a fresh server-minted session at `start`.
  let session = await resumeOrStartSession(start);
  if (session && session.synthetic) {
    await adoptSessionField(session);
  } else if (session && (session.field !== App.field || !el("page-select").querySelector(`option[value="${CSS.escape(session.active_page)}"]`))) {
    session = await resumeOrStartSession(start, { new: true }); // the stored journey is in another field
  }
  if (session) {
    await showPage(session.active_page);
    syncHistoryEntry(session.encounter_count - 1);
    if (session.resumed) App.navLogged = logNavigation("page_viewed", { page_id: session.active_page, via: "reload" }); // legacy line; no encounter anywhere
  } else {
    await showPage(start); // no Core session could be started: the page is shown, nothing is recorded
    setMoveStatus(`No Core session could be started (${App.sessionError || "unknown error"}); ${start} is shown but nothing is recorded until one starts.`, "error");
  }
  renderTraversalHistory(readerState);
  // Reload: show again the operator list the reader had open at this revision (a GET only,
  // and the same persisted offer set: resolving again at one revision creates nothing).
  const current = App.session && App.session.current_offer_sets ? App.session.current_offer_sets : [];
  const lastOffer = [...current].reverse().find((o) => o.operator && o.policy === App.policy);
  if (lastOffer && App.session.active_page === App.source) {
    await selectOperator(lastOffer.operator);  // never under a policy the reader did not choose
  } else {
    const lastOptions = readerState.last_operator_options;
    if (lastOptions && lastOptions.page_id === App.source && lastOptions.field === App.field &&
        lastOptions.policy === App.policy && lastOptions.operator) {
      await selectOperator(lastOptions.operator);
    }
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

async function showPage(pageId) {
  // Render a page the Core has already committed (or resumed) as the session's position.
  // Rendering only: no session-log line, no session start, no history entry. Every
  // arrival reaches here through relocate(), afterFollow(), startNewJourney() or a resume.
  if (!pageId) return false;
  App.navGeneration++;
  const myGeneration = App.navGeneration;
  App.visitId = randomId();
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
  const page = await api(`/api/page?field=${encodeURIComponent(App.field)}&id=${encodeURIComponent(pageId)}&session_id=${encodeURIComponent(App.session ? App.session.session_id : "")}`);
  if (myGeneration !== App.navGeneration) return false; // a newer navigation superseded this one

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
  el("new-journey-confirm").hidden = true;
  updateOperatorBadges();
  renderOptions();
  renderOperatorPanel();
  renderOffers();
  renderScore();

  // No session-log line here: every arrival's line is the projector's mirror of the Core
  // event (a resume's legacy `via=reload` line is written by init, once).
  loadLatestOffers();
  if (el("atlas-details").open) loadAtlas();
  return true;
}

async function onBack() {
  // In-app Back: a relocation (cause `back`) to the page on top of this tab's stack. The
  // stack entry is taken only once the Core has committed the move.
  if (App.viewHistory.length === 0) return;
  const prev = App.viewHistory[App.viewHistory.length - 1];
  const outcome = await relocate(prev, "back");
  if (outcome && App.viewHistory[App.viewHistory.length - 1] === prev) {
    App.viewHistory.pop();
    saveViewHistory();
    el("back-btn").disabled = App.viewHistory.length === 0;
  }
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
  el("operator-criterion").textContent = isDemo()
    ? "These relationships are declared for the synthetic material. The current part of the demonstration determines which choices are available."
    : App.criteria[operator] || "";
  el("postfollow-panel").hidden = true;
  updateOperatorBadges();
  renderOptions();
  renderOperatorPanel();
  loadEarlier(operator);
  if (!App.options[operator] || isDemo()) await loadOptions(operator);
}

async function loadOptions(operator) {
  // The Core's offer set at the session's current revision: the ordered bonds, each with its
  // exact offered wording. Resolving twice at one revision returns the same set.
  const ctx = snapshotContext();
  App.options[operator] = { loading: true };
  if (App.operator === operator) renderOptions();
  let data;
  await App.sessionReady;
  if (!stillCurrent(ctx)) return;
  const session = App.session;
  if (!session || session.active_page !== ctx.source) {
    data = { state: "error", options: [], counts: {}, message: `No Core session is at ${ctx.source}${App.sessionError ? ` (${App.sessionError})` : ""}. Any Previous, Next or page-list click brings the journey here first; click the operator again to retry.`, ordering_line: "" };
  } else {
    try {
      data = await postJson("/api/core/options", { session_id: session.session_id, operator, policy: ctx.policy });
      data.options = data.bonds; // the same row UI as before: one row per offered bond
      data.page_id = data.source_page;
    } catch (e) {
      const code = e.data && e.data.code;
      const message = code === "paused"
        ? "The session is paused, so no destinations are offered and no move is recorded: resume it to keep navigating."
        : `The ranked destinations could not be loaded: ${e.message}. Click the operator again to retry.`;
      data = { state: "error", code, options: [], counts: {}, message, ordering_line: "" };
    }
  }
  if (!stillCurrent(ctx)) return;
  if (typeof data.current_revision === "number" && App.session && App.session.session_id === data.session_id && App.session.revision !== data.current_revision) {
    refreshSession();
  } else if (data.score && App.session && App.session.session_id === data.session_id) {
    applySession({ ...App.session, score: data.score });
  }
  App.options[operator] = data;
  if (App.operator === operator) renderOptions();
  if (data.state === "error") delete App.options[operator]; // a later click retries
}

const CAUTION_TEXT = {
  low_confidence: "low confidence in this assessment",
  high_redundancy: "may largely repeat this page",
  high_missing_context: "may need context you have not read",
  low_direct_q_fit: "weak direct fit as a next page",
  synthetic_fixture_not_a_model_assessment: "Invented relationship for this demonstration",
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
    evidence: data.evidence_note || "decision evidence (model distribution) — no textual evidence span recorded",
    base_profile_scores: base, base_assessment_id: option.assessment_id,
    is_authored_neighbor: option.is_authored_neighbor, rank_reasons: option.rank_reasons,
    bond_version_id: option.bond_version_id, source_version: option.source_version, destination_version: option.destination_version,
    wording: option.wording, wording_source: option.wording_source,
    score_decisions: (data.decisions || []).filter((decision) => decision.bond_version_id === option.bond_version_id),
    offer_set_id: data.offer_set_id, offer_set_revision: data.revision, session_id: data.session_id,
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
  if (typeof option.wording === "string" && option.wording) {
    // The exact sentence this bond offers (this session: the destination's own opening sentence, verbatim).
    const wording = textNode("blockquote", `Offered: «${option.wording}»`, "option-wording");
    wording.dataset.testid = "option-wording";
    wording.title = option.wording_source === "destination_opening_sentence" ? "the destination's opening sentence, quoted exactly" : (option.wording_source || "");
    row.appendChild(wording);
  }
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
  list.dataset.offerSetId = data.offer_set_id || "";
  list.dataset.revision = typeof data.revision === "number" ? String(data.revision) : "";
  list.dataset.sessionId = data.session_id || "";
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
  const excluded = (data.decisions || []).filter((decision) => !decision.allowed);
  if (excluded.length) {
    const explanation = document.createElement("details");
    explanation.dataset.testid = "score-exclusions";
    explanation.open = isDemo();
    explanation.appendChild(textNode("summary", "Why other choices are unavailable"));
    for (const decision of excluded) {
      const descriptions = {
        target_already_visited: "Already visited on this journey; choose a passage you have not visited yet.",
        target_not_entry_version: "This part asks you to return to the starting passage.",
        return_too_soon: "The return needs more arrivals between visits.",
        target_not_previously_encountered: "A return only applies to a passage already visited on this journey.",
        operator_forbidden: "This kind of choice is unavailable in the current part of the demonstration.",
      };
      const reason = descriptions[decision.code] || decision.reason || decision.code.replaceAll("_", " ");
      explanation.appendChild(textNode("p", `${decision.destination_page || decision.candidate_id}: ${reason}`));
    }
    list.appendChild(explanation);
  }

  const canRefine = !isDemo() && (data.options || []).length > 0 && !!(data.offer_set_id || data.option_set_id);
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
    offer_set_id: data.offer_set_id, offer_set_revision: data.revision, session_id: data.session_id,
    source_version: data.source_version, options_policy_version: data.options_policy_version,
    reused_offer_set: data.reused, exclusions: data.exclusions, evidence: data.evidence_note,
    score_config_sha256: data.score_config_sha256, decisions: data.decisions, blocked: data.blocked,
    option_set_id: data.option_set_id, page_sha256: data.page_sha256, refinement: data.refinement,
  }, null, 2);
}

async function onRefineOptions() {
  if (isDemo()) return;
  const operator = App.operator;
  const shown = App.options[operator];
  if (!operator || !shown || !(shown.offer_set_id || shown.option_set_id)) return;
  const key = ["refine", App.field, App.source, operator, App.policy, shown.offer_set_id || shown.option_set_id].join("|");
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
    // The refinement is keyed on the legacy ranked option set, which is read (and persisted,
    // idempotently) only here, at this explicit click -- never when the offers are shown. It
    // must list exactly the destinations on screen, in the same base order.
    let optionSetId = shown.option_set_id;
    if (!optionSetId) {
      const legacy = await api(
        `/api/operator-options?field=${encodeURIComponent(ctx.field)}&page=${encodeURIComponent(ctx.source)}` +
        `&operator=${encodeURIComponent(operator)}&policy=${encodeURIComponent(ctx.policy)}`);
      const legacyIds = (legacy.options || []).map((o) => o.destination_id);
      const shownIds = (shown.options || []).map((o) => o.destination_id);
      if (!legacy.option_set_id || legacyIds.join("|") !== shownIds.join("|")) {
        throw new Error("the saved ranked list does not match the offered bonds, so nothing was refined");
      }
      optionSetId = legacy.option_set_id;
    }
    data = await postJson("/api/refine-options", { option_set_id: optionSetId, request_id: requestId });
    data.legacy_option_set_id = optionSetId;
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
  if (!current || (current.offer_set_id || current.option_set_id) !== (shown.offer_set_id || shown.option_set_id)) return;

  const byDestination = new Map((current.options || []).map((o) => [o.destination_id, o]));
  const usable = data.refine_state === "refined" && data.applicable !== false && data.memory_current !== false &&
    Array.isArray(data.options) && data.options.length === (current.options || []).length &&
    data.options.every((o) => byDestination.has(o.destination_id));
  if (usable) {
    // The same offered bonds (same offer set, same ids, same wording), shown in the refined
    // order with each one's history-conditioned answers; nothing is added or removed.
    App.options[operator] = {
      ...current, ordering_basis: data.ordering_basis, order_changed: data.order_changed, ordering_line: data.ordering_line,
      refinement: data.refinement, option_set_id: data.legacy_option_set_id || current.option_set_id,
      options: data.options.map((o) => ({ ...byDestination.get(o.destination_id), contextual: o.contextual, contextual_error: o.contextual_error })),
    };
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
  // An offer set belongs to the session, page and revision it was resolved at; never
  // follow it from anywhere else.
  if (data.page_id !== App.source || data.field !== App.field || !data.offer_set_id) return;
  App.following = true; // set before any await: a double click is one click
  renderOptions();
  const ctx = snapshotContext();
  const operator = App.operator;
  // One request_id per click. It is reused only when that same click got NO response
  // (network failure), so a retry is the same action and the Core answers with its
  // recorded result instead of a second traversal.
  const attemptKey = `${data.offer_set_id}|${option.bond_version_id}`;
  const requestId = App.executeAttempts[attemptKey] || newRequestId();
  App.executeAttempts[attemptKey] = requestId;
  let outcome = null;
  let error = null;
  try {
    await App.sessionReady;
    if (!App.session || App.session.session_id !== data.session_id) {
      throw Object.assign(new Error("these options belong to another journey; choose the operator again"), { status: 0, data: { code: "session_changed" } });
    }
    await App.navLogged;
    outcome = await postJson("/api/core/execute", {
      session_id: data.session_id, offer_set_id: data.offer_set_id, bond_version_id: option.bond_version_id,
      expected_revision: data.revision, request_id: requestId,
    });
  } catch (e) {
    error = e;
  } finally {
    App.following = false;
  }
  if (!error || error.status !== undefined) delete App.executeAttempts[attemptKey]; // answered: the next click is a new action
  if (!stillCurrent(ctx)) return;

  if (outcome) {
    if (outcome.session) applySession(outcome.session);
    await afterFollow({ proposal_id: null, bond_id: outcome.bond_version_id, reader_state: outcome.reader_state },
                      outcome.to_page || option.destination_id, null, outcome.encounter_index);
    if (outcome.duplicate) el("postfollow-panel").querySelector("h2").appendChild(textNode("span", " (this click was already recorded; nothing moved twice)", "kind-note"));
    return;
  }

  const refusal = error.data || {};
  const statusEl = el("options-status");
  statusEl.className = "status-line state-error";
  statusEl.dataset.refusal = refusal.code || "";
  if (refusal.session) applySession(refusal.session);
  if (refusal.code === "stale_revision") {
    const session = refusal.session || App.session;
    const where = session ? ` (at ${session.active_page}, ${session.encounter_count} encounter${session.encounter_count === 1 ? "" : "s"})` : "";
    statusEl.textContent = `Not followed — you have not moved. These options were offered at revision ${data.revision}, but the session is now at revision ${refusal.current_revision}${where}. `;
    if (session && session.active_page === App.source) {
      statusEl.appendChild(textNode("span", "The options were re-resolved at the current revision."));
      delete App.options[operator];
      renderOptions();
      await loadOptions(operator);
    } else {
      renderOptions();
      showCoreSessionConflict(session);
    }
    return;
  }
  renderOptions();
  if (refusal.code === "paused") {
    statusEl.textContent = "Not followed — you have not moved. The session is paused; resume it (above) to keep navigating.";
    return;
  }
  const reason = refusal.reason || error.message;
  statusEl.textContent = `Not followed — you have not moved. ${reason}`;
  if (error.status === undefined) {
    statusEl.appendChild(textNode("span", " No response arrived; clicking Follow again retries this same action (same request id)."));
  } else if (["unknown_or_stale_offer_set", "not_offered", "source_mismatch", "destination_version_changed", "source_version_changed", "policy_ineligible", "session_changed"].includes(refusal.code)) {
    delete App.options[operator];
    await loadOptions(operator);
  }
}

async function continueHere() {
  // "Continue here on <this page>": an intentional move of the SAME journey back to the
  // page this tab shows (cause `resume_here`). The reader has just been told the journey
  // moved on elsewhere, so the session view is re-read first and the relocation is made
  // against the current revision; the Core still decides (a no-op if it is already here).
  const here = App.source;
  const operator = App.operator;
  await refreshSession();
  const outcome = await relocate(here, "resume_here");
  if (outcome && outcome.noop && App.session && App.session.position && App.session.position.agrees === false) {
    // The journey was already here; only the legacy session log placed the reader elsewhere.
    App.navLogged = logNavigation("page_viewed", { page_id: here, via: "resume" });
    await App.navLogged;
  }
  if (!outcome || App.source !== here) return outcome;
  App.operator = operator; // showPage cleared the panels; the reader's operator choice is kept
  if (operator) { delete App.refine[operator]; delete App.options[operator]; }
  updateOperatorBadges();
  renderOptions();
  renderOffers();
  renderOperatorPanel();
  if (operator) { el("operator-criterion").hidden = false; el("operator-criterion").textContent = App.criteria[operator] || ""; loadOptions(operator); }
  return outcome;
}

function showCoreSessionConflict(session) {
  // The Core session moved on (another tab or window moved it). Nothing here has moved.
  // The reader chooses: continue reading HERE (a relocation of the same journey back to
  // this page), or go to where the journey is (a relocation that is a no-op there).
  const box = el("position-conflict");
  box.replaceChildren();
  box.hidden = false;
  const sessionPage = session ? session.active_page : null;
  box.appendChild(textNode("p", sessionPage
    ? `Nothing was followed and nothing has moved. This tab shows ${App.source}, but the journey moved on to ${sessionPage} (revision ${session.revision}; another tab or window moved it). Choose "Continue here on ${App.source}" to bring the journey back to this page (one recorded manual move), then choose the action again yourself, or go to ${sessionPage}.`
    : `Nothing was followed and nothing has moved. The journey is no longer at ${App.source}. Choose "Continue here on ${App.source}" to bring the journey back to this page (one recorded manual move), then choose the action again yourself.`));
  const actions = document.createElement("div");
  actions.className = "action-row";
  const here = textNode("button", `Continue here on ${App.source}`);
  here.dataset.testid = "conflict-continue-here";
  here.addEventListener("click", async () => {
    here.disabled = true;
    box.hidden = true;
    await continueHere();
  });
  actions.appendChild(here);
  if (sessionPage) {
    const go = textNode("button", `Go to ${sessionPage}`);
    go.dataset.testid = "conflict-go-to-other";
    go.addEventListener("click", () => {
      box.hidden = true;
      relocate(sessionPage, "other");
    });
    actions.appendChild(go);
  }
  box.appendChild(actions);
  box.scrollIntoView({ block: "center" });
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
    box.hidden = true;
    await continueHere(); // the same journey, brought back here through the Core (a no-op if it is here)
  });
  actions.appendChild(here);
  if (conflict.logged_page) {
    const go = textNode("button", `Go to ${conflict.logged_page}`);
    go.dataset.testid = "conflict-go-to-other";
    go.addEventListener("click", () => {
      box.hidden = true;
      relocate(conflict.logged_page, "other");
    });
    actions.appendChild(go);
  }
  box.appendChild(actions);
  box.scrollIntoView({ block: "center" });
  return true;
}

// --- single pick (research): the secondary, explicit Choice request ---

async function singlePick(operator) {
  if (isDemo()) return;
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
  if (isDemo()) return;
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
  if (isDemo()) { el("result-panel").hidden = true; return; }
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
  if (isDemo()) return;
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

async function afterFollow(outcome, destination, runDir, encounterIndex) {
  // `encounterIndex` is set when the Core committed the arrival (a followed bond): the
  // page is rendered and one history entry is pushed. The legacy research paths
  // (single pick, advanced hand) moved the reader without the Core, so the journey is
  // brought along with a manual relocation (cause `other`) -- an arrival with no Core
  // bond asserted, rendered as whatever the Core commits.
  App.currentBond = { proposal_id: outcome.proposal_id, bond_id: outcome.bond_id };
  const bond = App.currentBond;
  renderTraversalHistory(outcome.reader_state);
  const previous = App.source;
  if (typeof encounterIndex === "number") {
    if (previous && previous !== destination) { App.viewHistory.push(previous); saveViewHistory(); }
    await showPage(destination);
    recordArrival(encounterIndex);
  } else {
    const moved = await relocate(destination, "other");
    if (!moved) return;
  }
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
      session_id: App.session && App.session.session_id,
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
  if (isDemo()) return;
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
  if (isDemo()) return;
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
      session_id: App.session && App.session.session_id,
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
  if (isDemo()) return;
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
