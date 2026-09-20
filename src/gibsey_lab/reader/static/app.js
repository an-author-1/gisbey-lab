"use strict";

const App = {
  field: null,
  source: null,
  operator: null,
  currentRun: null,   // {run_dir, recorded, is_abstention, selected_id, selected_text, ...}
  currentBond: null,  // {proposal_id, bond_id}
  viewHistory: [],    // client-side "pages I looked at" for the Back button only
  criteria: {},       // operator -> exact criterion text, from /api/fields
};

const el = (id) => document.getElementById(id);

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function renderPassage(container, text) {
  container.innerHTML = "";
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
  for (const p of paragraphs) {
    const el2 = document.createElement("p");
    el2.textContent = p;
    container.appendChild(el2);
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
  App.criteria = fieldsData.criteria;
  renderOperatorButtons(fieldsData.operators, fieldsData.operator_version);

  fieldSelect.addEventListener("change", async () => {
    App.field = fieldSelect.value;
    await loadPageList();
    const first = App.field === "holdout-21" ? "PR1" : (el("page-select").options[0] || {}).value;
    await navigateTo(first, false);
  });
  el("back-btn").addEventListener("click", onBack);
  el("page-select").addEventListener("change", () => navigateTo(el("page-select").value, false));
  el("request-new-btn").addEventListener("click", onRequestNew);
  el("accept-follow-btn").addEventListener("click", onAcceptAndFollow);
  el("preserve-btn").addEventListener("click", onPreserve);
  el("save-note-btn").addEventListener("click", onSaveNote);

  await loadPageList();

  // Start at PR1 unless there is already a recorded reader position (Q traversal state).
  const readerState = await api("/api/reader-state");
  const start = readerState.active_page && readerState.active_passage ? readerState.active_passage
    : (readerState.active_page || "PR1");
  await navigateTo(start, false);
  renderTraversalHistory(readerState);
}

async function loadPageList() {
  const data = await api(`/api/pages?field=${encodeURIComponent(App.field)}`);
  const pageSelect = el("page-select");
  pageSelect.innerHTML = "";
  for (const id of data.pages) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = id;
    pageSelect.appendChild(opt);
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

async function navigateTo(pageId, fromBack) {
  if (!pageId) return;
  if (!fromBack && App.source && App.source !== pageId) {
    App.viewHistory.push(App.source);
    el("back-btn").disabled = App.viewHistory.length === 0;
  }
  App.source = pageId;
  App.operator = null;
  App.currentRun = null;
  App.currentBond = null;

  el("page-select").value = pageId;
  const page = await api(`/api/page?field=${encodeURIComponent(App.field)}&id=${encodeURIComponent(pageId)}`);
  el("source-id").textContent = page.id;
  renderPassage(el("source-text"), page.text);

  document.querySelectorAll("#operator-buttons button").forEach((b) => b.classList.remove("active"));
  el("operator-criterion").hidden = true;
  el("result-panel").hidden = true;
  el("postfollow-panel").hidden = true;
}

async function onBack() {
  if (App.viewHistory.length === 0) return;
  const prev = App.viewHistory.pop();
  el("back-btn").disabled = App.viewHistory.length === 0;
  await navigateTo(prev, true);
}

async function selectOperator(operator) {
  App.operator = operator;
  document.querySelectorAll("#operator-buttons button").forEach((b) => {
    b.classList.toggle("active", b.dataset.operator === operator);
  });

  el("operator-criterion").hidden = false;
  el("operator-criterion").textContent = App.criteria[operator] || "";

  el("result-panel").hidden = false;
  el("postfollow-panel").hidden = true;
  el("result-status").textContent = "Checking for a recorded result...";
  el("result-status").className = "status-line";
  el("result-body").innerHTML = "";
  el("tech-details").hidden = true;
  el("result-actions").hidden = true;

  const saved = await api(
    `/api/saved-result?field=${encodeURIComponent(App.field)}&source=${encodeURIComponent(App.source)}&operator=${encodeURIComponent(operator)}`
  );

  if (saved.recorded) {
    App.currentRun = saved;
    renderResult(saved, "recorded");
  } else {
    App.currentRun = null;
    el("result-status").textContent = "No recorded original-field result for this combination.";
    el("result-body").innerHTML = "";
    el("result-actions").hidden = false;
    el("accept-follow-btn").disabled = true;
  }
  el("result-actions").hidden = false;
}

function renderResult(record, kind) {
  // kind: "recorded" | "new"
  const statusEl = el("result-status");
  const bodyEl = el("result-body");
  const actionsEl = el("result-actions");
  actionsEl.hidden = false;

  if (record.error) {
    statusEl.textContent = `Error (${kind === "recorded" ? "recorded" : "live"} run): ${record.error}`;
    statusEl.className = "status-line status-error";
    bodyEl.innerHTML = "";
    el("accept-follow-btn").disabled = true;
  } else if (record.is_abstention) {
    statusEl.textContent = `${kind === "recorded" ? "Recorded result" : "New live result"}: Jev abstained (NONE) -- no eligible destination.`;
    statusEl.className = "status-line status-none";
    bodyEl.innerHTML = "";
    el("accept-follow-btn").disabled = true;
  } else {
    statusEl.textContent = kind === "recorded" ? "Recorded result" : "New live result (just requested)";
    statusEl.className = `status-line ${kind === "recorded" ? "status-recorded" : ""}`;
    bodyEl.innerHTML = `<h3>${record.selected_id}</h3>`;
    const passageDiv = document.createElement("div");
    passageDiv.className = "passage";
    renderPassage(passageDiv, record.selected_text);
    bodyEl.appendChild(passageDiv);
    el("accept-follow-btn").disabled = false;
  }

  el("tech-details").hidden = false;
  el("tech-details-body").textContent = JSON.stringify(
    {
      run_id: record.run_id,
      run_dir: record.run_dir,
      field: record.field,
      source: record.source,
      operator: record.operator,
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
}

async function onRequestNew() {
  el("request-new-btn").disabled = true;
  el("result-status").textContent = "Requesting a live selection from Jev...";
  el("result-status").className = "status-line";
  try {
    const record = await api("/api/request-selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field: App.field, source: App.source, operator: App.operator }),
    });
    if (record.result) {
      renderResult(
        {
          ...record.result,
          run_id: record.run_id,
          run_dir: record.run_dir,
          field: record.field,
          source: record.source,
          operator: record.operator,
          criterion: record.criterion,
          requested_model: record.requested_model,
          returned_model: record.returned_model,
          elapsed_seconds: record.elapsed_seconds,
          usage: record.usage,
        },
        "new"
      );
    } else {
      renderResult({ ...record, error: record.error || "unknown error" }, "new");
    }
  } catch (e) {
    el("result-status").textContent = `Request failed: ${e.message}`;
    el("result-status").className = "status-line status-error";
  } finally {
    el("request-new-btn").disabled = false;
  }
}

async function onAcceptAndFollow() {
  if (!App.currentRun || !App.currentRun.run_dir) return;
  el("accept-follow-btn").disabled = true;
  try {
    const outcome = await api("/api/accept-and-follow", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_dir: App.currentRun.run_dir }),
    });
    App.currentBond = { proposal_id: outcome.proposal_id, bond_id: outcome.bond_id };
    renderTraversalHistory(outcome.reader_state);

    const destination = App.currentRun.selected_id;
    await navigateTo(destination, false);

    el("postfollow-panel").hidden = false;
    el("postfollow-id").textContent = destination;
    el("preserve-status").textContent = "";
    ["note-correspondence", "note-change"].forEach((id) => (el(id).value = ""));
    ["note-grounding", "note-effect", "note-decision"].forEach((id) => (el(id).value = ""));
  } catch (e) {
    el("result-status").textContent = `Accept/follow failed: ${e.message}`;
    el("result-status").className = "status-line status-error";
  } finally {
    el("accept-follow-btn").disabled = false;
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
