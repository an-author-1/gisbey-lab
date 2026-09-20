"use strict";

const App = {
  field: null,
  policy: null,
  source: null,
  operator: null,
  currentRun: null,   // {run_dir, recorded, is_abstention, selected_id, selected_text, ...}
  currentBond: null,  // {proposal_id, bond_id}
  viewHistory: [],    // client-side "pages I looked at" for the Back button only
  criteria: {},       // operator -> exact criterion text, from /api/fields
  followImmediately: false,
  generation: 0,      // bumped on every navigation/field/policy change; guards against stale async responses
  currentPage: null,  // {id, previous_id, next_id} for the active source
};

const el = (id) => document.getElementById(id);

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function logNavigation(event, extra) {
  api("/api/session/navigation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, field: App.field, ...extra }),
  }).catch(() => {}); // passive logging: never blocks or breaks the reading flow
}

function renderPassage(container, text) {
  container.innerHTML = "";
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  for (const p of paragraphs) {
    const p2 = document.createElement("p");
    p2.textContent = p;
    container.appendChild(p2);
  }
}

async function init() {
  const fieldsData = await api("/api/fields");

  const fieldSelect = el("field-select");
  fieldSelect.innerHTML = "";
  for (const f of fieldsData.fields) {
    const opt = document.createElement("option");
    opt.value = f.id;
    opt.textContent = f.label;
    if (f.default) opt.selected = true;
    fieldSelect.appendChild(opt);
  }
  App.field = fieldsData.fields.find((f) => f.default).id;

  const policySelect = el("policy-select");
  policySelect.innerHTML = "";
  for (const p of fieldsData.policies) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.label;
    if (p.default) opt.selected = true;
    policySelect.appendChild(opt);
  }
  App.policy = fieldsData.policies.find((p) => p.default).id;

  App.criteria = fieldsData.criteria;
  renderOperatorButtons(fieldsData.operators, fieldsData.operator_version);

  fieldSelect.addEventListener("change", async () => {
    const previousField = App.field;
    App.field = fieldSelect.value;
    App.generation++;
    App.viewHistory = [];
    el("back-btn").disabled = true;
    logNavigation("field_selected", { from_field: previousField });
    await checkFieldStatus();
    await loadPageList();
    const groups = el("page-select").querySelectorAll("optgroup");
    const firstPage = groups.length ? groups[0].querySelector("option").value : null;
    await navigateTo(firstPage, "dropdown");
  });
  policySelect.addEventListener("change", () => {
    App.policy = policySelect.value;
    App.generation++; // any in-flight saved-result/request-selection under the old policy is now stale
    el("policy-badge").textContent = App.policy;
    // Re-check the current operator (if any) under the new policy, without moving the reader.
    if (App.operator) selectOperator(App.operator);
  });
  el("back-btn").addEventListener("click", onBack);
  el("prev-btn").addEventListener("click", () => {
    if (App.currentPage && App.currentPage.previous_id) navigateTo(App.currentPage.previous_id, "prev_next");
  });
  el("next-btn").addEventListener("click", () => {
    if (App.currentPage && App.currentPage.next_id) navigateTo(App.currentPage.next_id, "prev_next");
  });
  el("page-select").addEventListener("change", () => navigateTo(el("page-select").value, "dropdown"));
  el("follow-immediately-toggle").addEventListener("change", (e) => {
    App.followImmediately = e.target.checked;
  });
  el("request-new-btn").addEventListener("click", () => onRequestNew());
  el("accept-follow-btn").addEventListener("click", () => onAcceptAndFollow());
  el("preserve-btn").addEventListener("click", onPreserve);
  el("save-note-btn").addEventListener("click", onSaveNote);

  await checkFieldStatus();
  await loadPageList();

  // Start at the recorded reader position if one exists (a real Q traversal already
  // happened in a previous session), otherwise the first page of the default field.
  const readerState = await api("/api/reader-state");
  let start = readerState.active_passage || readerState.active_page;
  if (!start) {
    const firstGroup = el("page-select").querySelector("optgroup");
    start = firstGroup ? firstGroup.querySelector("option").value : null;
  }
  await navigateTo(start, "dropdown");
  renderTraversalHistory(readerState);
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
  pageSelect.innerHTML = "";
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
  row.innerHTML = "";
  for (const op of operators) {
    const btn = document.createElement("button");
    btn.textContent = op;
    btn.dataset.operator = op;
    btn.title = `Q Operator Prototype ${version}`;
    btn.addEventListener("click", () => selectOperator(op));
    row.appendChild(btn);
  }
}

async function navigateTo(pageId, via) {
  if (!pageId) return;
  App.generation++;
  const myGeneration = App.generation;

  const isBack = via === "back";
  if (!isBack && App.source && App.source !== pageId) {
    App.viewHistory.push(App.source);
    el("back-btn").disabled = App.viewHistory.length === 0;
  }
  App.source = pageId;
  App.operator = null;
  App.currentRun = null;
  App.currentBond = null;

  el("page-select").value = pageId;
  const page = await api(`/api/page?field=${encodeURIComponent(App.field)}&id=${encodeURIComponent(pageId)}`);
  if (myGeneration !== App.generation) return; // a newer navigation superseded this one

  App.currentPage = page;
  el("source-id").textContent = page.id;
  el("field-badge").textContent = App.field;
  el("policy-badge").textContent = App.policy;
  el("prev-btn").disabled = !page.previous_id;
  el("prev-btn").textContent = page.previous_id ? `← Previous (${page.previous_id})` : "← Previous";
  el("next-btn").disabled = !page.next_id;
  el("next-btn").textContent = page.next_id ? `Next (${page.next_id}) →` : "Next →";
  renderPassage(el("source-text"), page.text);

  document.querySelectorAll("#operator-buttons button").forEach((b) => b.classList.remove("active"));
  el("operator-criterion").hidden = true;
  el("result-panel").hidden = true;
  el("postfollow-panel").hidden = true;

  logNavigation(isBack ? "back" : "page_viewed", { page_id: pageId, via: via || "dropdown" });
}

async function onBack() {
  if (App.viewHistory.length === 0) return;
  const prev = App.viewHistory.pop();
  el("back-btn").disabled = App.viewHistory.length === 0;
  await navigateTo(prev, "back");
}

async function selectOperator(operator) {
  App.generation++;
  const myGeneration = App.generation;

  App.operator = operator;
  document.querySelectorAll("#operator-buttons button").forEach((b) => {
    b.classList.toggle("active", b.dataset.operator === operator);
  });

  el("operator-criterion").hidden = false;
  el("operator-criterion").textContent = App.criteria[operator] || "";

  el("result-panel").hidden = false;
  el("postfollow-panel").hidden = true;
  el("result-status").textContent = "Loading — checking for a recorded result...";
  el("result-status").className = "status-line status-loading";
  el("result-body").innerHTML = "";
  el("tech-details").hidden = true;
  el("result-actions").hidden = true;
  disableResultButtons(true);

  const field = App.field, source = App.source, policy = App.policy;
  const saved = await api(
    `/api/saved-result?field=${encodeURIComponent(field)}&source=${encodeURIComponent(source)}` +
    `&operator=${encodeURIComponent(operator)}&policy=${encodeURIComponent(policy)}`
  );
  if (myGeneration !== App.generation) return; // stale: field/page/operator/policy changed since this click

  el("result-actions").hidden = false;
  disableResultButtons(false);

  if (saved.recorded) {
    App.currentRun = saved;
    renderResult(saved, "recorded");
    if (App.followImmediately) await tryAutoFollow(myGeneration);
  } else {
    // Clicking an operator must always produce a proposal: no recorded match means an
    // automatic live request, in both Preview and Follow-immediately mode. This is the
    // fix for "uncached choices require an extra request" -- there is no separate click
    // needed just to discover that nothing was cached.
    await onRequestNew(myGeneration);
  }
}

function disableResultButtons(disabled) {
  el("request-new-btn").disabled = disabled;
  el("accept-follow-btn").disabled = disabled || !App.currentRun || App.currentRun.error || App.currentRun.is_abstention;
}

function renderResult(record, kind) {
  // kind: "recorded" | "new" | "mock"
  const statusEl = el("result-status");
  const bodyEl = el("result-body");

  const kindLabel = { recorded: "Recorded result", new: "New live result (just requested)", mock: "MOCK result (not a real Jev call)" }[kind] || kind;

  if (record.error) {
    statusEl.textContent = `Error (${kindLabel}): ${record.error}`;
    statusEl.className = "status-line status-error";
    bodyEl.innerHTML = "";
  } else if (record.is_abstention) {
    statusEl.textContent = `${kindLabel}: Jev abstained (NONE) -- no eligible destination.`;
    statusEl.className = "status-line status-none";
    bodyEl.innerHTML = "";
  } else {
    statusEl.textContent = kindLabel;
    statusEl.className = `status-line kind-${kind}`;
    bodyEl.innerHTML = `<h3>${record.selected_id}</h3>`;
    const passageDiv = document.createElement("div");
    passageDiv.className = "passage";
    renderPassage(passageDiv, record.selected_text);
    bodyEl.appendChild(passageDiv);
  }

  el("tech-details").hidden = false;
  el("tech-details-body").textContent = JSON.stringify(
    {
      run_id: record.run_id,
      run_dir: record.run_dir,
      field: record.field,
      source: record.source,
      operator: record.operator,
      policy: App.policy,
      criterion: record.criterion,
      confidence: record.confidence,
      probabilities: record.probabilities,
      requested_model: record.requested_model,
      returned_model: record.returned_model,
      elapsed_seconds: record.elapsed_seconds,
      usage: record.usage,
    },
    null,
    2
  );

  App.currentRun = { ...record, run_dir: record.run_dir };
  disableResultButtons(false);
}

async function onRequestNew(expectedGeneration) {
  // Reserved for an explicit rerun when called from the "Ask Jev again" button (no
  // argument); also used internally as the automatic first request on a cache miss.
  const myGeneration = typeof expectedGeneration === "number" ? expectedGeneration : App.generation;
  const field = App.field, source = App.source, operator = App.operator, policy = App.policy;

  disableResultButtons(true);
  el("result-status").textContent = "Loading — requesting a live selection from Jev...";
  el("result-status").className = "status-line status-loading";
  try {
    const record = await api("/api/request-selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, source, operator, policy }),
    });
    if (myGeneration !== App.generation) return; // stale: navigation/policy change happened while this was in flight

    if (record.result) {
      renderResult(
        {
          ...record.result,
          run_id: record.run_id, run_dir: record.run_dir, field: record.field,
          source: record.source, operator: record.operator, criterion: record.criterion,
          requested_model: record.requested_model, returned_model: record.returned_model,
          elapsed_seconds: record.elapsed_seconds, usage: record.usage,
        },
        record.kind || "new"
      );
      if (App.followImmediately) await tryAutoFollow(myGeneration);
    } else {
      renderResult({ ...record, error: record.error || "unknown error" }, record.kind || "new");
    }
  } catch (e) {
    if (myGeneration === App.generation) {
      el("result-status").textContent = `Request failed: ${e.message}`;
      el("result-status").className = "status-line status-error";
      disableResultButtons(false);
    }
  }
}

async function tryAutoFollow(expectedGeneration) {
  if (expectedGeneration !== App.generation) return;
  if (!App.currentRun || App.currentRun.error || App.currentRun.is_abstention) return;
  el("result-status").textContent += " — following automatically (Follow immediately mode)...";
  await onAcceptAndFollow(expectedGeneration);
}

async function onAcceptAndFollow(expectedGeneration) {
  const myGeneration = typeof expectedGeneration === "number" ? expectedGeneration : App.generation;
  if (myGeneration !== App.generation) return;
  if (!App.currentRun || !App.currentRun.run_dir) return;

  el("accept-follow-btn").disabled = true;
  const field = App.field, source = App.source, operator = App.operator;
  try {
    const outcome = await api("/api/accept-and-follow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_dir: App.currentRun.run_dir, field, source, operator }),
    });
    if (myGeneration !== App.generation) return; // a newer navigation/field-change superseded this

    App.currentBond = { proposal_id: outcome.proposal_id, bond_id: outcome.bond_id };
    renderTraversalHistory(outcome.reader_state);

    const destination = App.currentRun.selected_id;
    await navigateTo(destination, "traversal");

    el("postfollow-panel").hidden = false;
    el("postfollow-id").textContent = destination;
    el("preserve-status").textContent = "";
    ["note-correspondence", "note-change"].forEach((id) => (el(id).value = ""));
    ["note-grounding", "note-effect", "note-decision"].forEach((id) => (el(id).value = ""));
  } catch (e) {
    if (myGeneration === App.generation) {
      el("result-status").textContent = `Accept/follow failed: ${e.message}`;
      el("result-status").className = "status-line status-error";
    }
  } finally {
    if (myGeneration === App.generation) {
      el("accept-follow-btn").disabled = false;
    }
  }
}

async function onPreserve() {
  if (!App.currentBond || !App.currentBond.bond_id) return;
  el("preserve-btn").disabled = true;
  try {
    const outcome = await api("/api/preserve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bond_id: App.currentBond.bond_id }),
    });
    el("preserve-status").textContent = `Preserved (vault entry ${outcome.entry_id}). Repeat-safe: clicking again returns the same entry.`;
  } catch (e) {
    el("preserve-status").textContent = `Preserve failed: ${e.message}`;
  } finally {
    el("preserve-btn").disabled = false;
  }
}

async function onSaveNote() {
  if (!App.currentRun || !App.currentRun.run_dir) return;
  const grounding = el("note-grounding").value;
  const effect = el("note-effect").value;
  try {
    await api("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_dir: App.currentRun.run_dir,
        correspondence: el("note-correspondence").value || null,
        reading_effect: el("note-change").value || null,
        grounding_score: grounding === "" ? null : parseInt(grounding, 10),
        effect_score: effect === "" ? null : parseInt(effect, 10),
        decision: el("note-decision").value || null,
      }),
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
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<p style="color:red">Failed to load reader: ${e.message}</p>`
  );
});
