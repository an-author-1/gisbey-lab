"""History-conditioned assessment of one candidate destination (Layer 3).

One provider request per candidate: the exact model-visible reading history, the current
page, the candidate page, and three independent Score questions. The answers are kept
separate everywhere downstream; they are never collapsed into one "interestingness" value.

Guarantees:
- The state identifies texts only by role key (`reading_history`, `current_page`,
  `candidate_destination`); no corpus page id or hash is sent. An empty history is the same
  well-formed request with an empty `encounters` list and a plain note saying so.
- Every outcome -- ok, invalid, error, budget_refused -- is appended to ASSESSMENTS_PATH
  with the exact state and questions sent. Nothing is ever rewritten or deleted.
- A stored record is reused ONLY on an exact cache-key match, same mode, status "ok",
  schema "contextual-assessment/1", layer "history_conditioned" (and the pinned returned
  model, when one is pinned). The returned copy is marked `from_cache=True`. An error or
  invalid record is never reused as a success, and a base pair profile can never be
  returned from here: it has a different schema, layer, store, and key.
- `mode` is whatever the dispatch stamped. If that differs from the mode the caller asked
  for, the record is stored as an error rather than silently relabeled.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..corpus import REPO_ROOT, Page
from ..scoring import Dispatch, ScoreOutcome, ScoreQuestion, ScoreRequest
from .packet import MEMORY_POLICY_VERSION, memory_sha256, model_visible_state

CONTEXTUAL_RUBRIC_VERSION = "contextual-rubric-v1"
ASSESSMENT_SCHEMA = "contextual-assessment/1"
LAYER = "history_conditioned"
ASSESSMENTS_PATH = REPO_ROOT / "data" / "contextual" / "assessments.jsonl"

QUESTION_IDS = ("works_after_history", "grounded_reading_effect", "repeats_recent_reading")

_FRAME = (
    "The state has three keys. `reading_history` lists the pages this reader encountered before the current "
    "one, oldest first, each with how the reader arrived at it; `reading_history.note` says whether earlier "
    "encounters were left out, `reading_history.current_page_arrived_by` says how the reader reached "
    "`current_page`, and `reading_history.reader_stated_intention`, when not null, is the reader's own "
    "statement of what they are reading for. `current_page` is the page the reader is on now. `candidate_destination` is a "
    "page the reader could move to next. Direction: the reader moves FROM `current_page` TO "
    "`candidate_destination`, having already read `reading_history`. If `reading_history.encounters` is "
    "empty, no earlier reading is supplied: judge the move from `current_page` alone and do not imagine a "
    "history. Having visited a page does not mean the reader liked it, agreed with it, or endorsed any "
    "interpretation of it. Judge only from the supplied texts. "
)

QUESTIONS: tuple[ScoreQuestion, ...] = (
    ScoreQuestion(
        qid="works_after_history",
        instructions=_FRAME + (
            "Question: for a reader who has read exactly `reading_history` and is now on `current_page`, how "
            "well does moving to `candidate_destination` work as the next step of reading? Consider what this "
            "particular history has and has not already put in front of the reader."
        ),
        levels=(
            "Does not work: after this history the move is arbitrary or disorienting; nothing in the supplied texts prepares or motivates it.",
            "Works weakly: a thin or incidental connection; the move is followable but this history gives it little point.",
            "Works: the move is prepared by `current_page` or by `reading_history`, and a reader with this history can see why it comes next.",
            "Works strongly: this specific history and `current_page` together make the move to `candidate_destination` clearly apt at this moment.",
        ),
    ),
    ScoreQuestion(
        qid="grounded_reading_effect",
        instructions=_FRAME + (
            "Question: how far would moving to `candidate_destination` add a reading effect that is supported "
            "by the texts -- something specific in `candidate_destination` that extends, answers, complicates, "
            "reverses, or reframes something specific in `current_page` or `reading_history`? Count only effects "
            "you could point to in the wording of the supplied texts, not general thematic resemblance."
        ),
        levels=(
            "No supported effect: nothing specific in `candidate_destination` acts on anything specific the reader has read.",
            "Slight effect: a general or loosely supported effect; the textual grounding is thin.",
            "Clear effect: a specific effect that can be pointed to in the wording of both `candidate_destination` and what the reader has read.",
            "Strong effect: a specific, well-grounded effect that materially changes how the already-read material reads.",
        ),
    ),
    ScoreQuestion(
        qid="repeats_recent_reading",
        instructions=_FRAME + (
            "Question: how much does `candidate_destination` merely repeat what this reader has just encountered "
            "in `reading_history` and `current_page`? Higher means MORE repetition. A page that already appears in "
            "`reading_history` is not automatically repetitive: judge whether, after the intervening reading, "
            "returning to it would give the reader something new or only the same material again."
        ),
        levels=(
            "No notable repetition: `candidate_destination` gives the reader material they have not just encountered.",
            "Some overlap: shared motifs or phrasing with what was just read, but mostly new material or a new use of it.",
            "Substantial repetition: much of `candidate_destination` restates what the reader has just encountered, with limited new material.",
            "Mostly repetition: `candidate_destination` would give this reader essentially the same material again with nothing new.",
        ),
    ),
)


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_contextual_request(packet: dict, current_text: str, candidate_text: str, requested_model: str) -> ScoreRequest:
    """`state["reading_history"]` is `model_visible_state(packet)` verbatim, so the hash in
    the cache key (`memory_sha256`) covers exactly the history the provider receives."""
    state = {
        "reading_history": model_visible_state(packet),
        "current_page": {"text": current_text},
        "candidate_destination": {"text": candidate_text},
    }
    return ScoreRequest(kind="contextual", state=state, questions=QUESTIONS, requested_model=requested_model)


def cache_key(*, current_sha256: str, candidate_sha256: str, memory_sha256: str, requested_model: str,
              pinned_returned_model: str | None, atlas_config_id: str | None,
              memory_policy_version: str = MEMORY_POLICY_VERSION,
              contextual_rubric_version: str = CONTEXTUAL_RUBRIC_VERSION) -> str:
    return hashlib.sha256(_canonical({
        "schema": ASSESSMENT_SCHEMA,
        "layer": LAYER,
        "current_sha256": current_sha256,
        "candidate_sha256": candidate_sha256,
        "memory_sha256": memory_sha256,
        "memory_policy_version": memory_policy_version,
        "contextual_rubric_version": contextual_rubric_version,
        "requested_model": requested_model,
        "pinned_returned_model": pinned_returned_model,
        "atlas_config_id": atlas_config_id,
    }).encode("utf-8")).hexdigest()


def read_records(store_path: Path | None = None) -> list[dict]:
    path = Path(store_path) if store_path is not None else ASSESSMENTS_PATH
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _append(record: dict, store_path: Path | None) -> None:
    path = Path(store_path) if store_path is not None else ASSESSMENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def find_reusable(key: str, mode: str, *, pinned_returned_model: str | None = None,
                  store_path: Path | None = None) -> dict | None:
    """The latest stored record that may stand in for a fresh call, or None."""
    for record in reversed(read_records(store_path)):
        if (
            record.get("schema") == ASSESSMENT_SCHEMA
            and record.get("layer") == LAYER
            and record.get("cache_key") == key
            and record.get("mode") == mode
            and record.get("status") == "ok"
            and (pinned_returned_model is None or record.get("returned_model") == pinned_returned_model)
        ):
            return record
    return None


def assess(packet: dict, *, current_page: Page, candidate_page: Page, dispatch: Dispatch, mode: str,
           requested_model: str, atlas_config_id: str | None, pinned_returned_model: str | None = None,
           reuse_cache: bool = True, store_path: Path | None = None) -> dict:
    """Assess one candidate against this exact memory. Returns the stored record plus
    `from_cache`. Exactly one provider request is made, or none on a cache hit."""
    if packet["current"]["sha256"] != current_page.sha256:
        raise ValueError("memory packet was built for a different version of the current page")

    mem_sha = memory_sha256(packet)
    key = cache_key(
        current_sha256=current_page.sha256, candidate_sha256=candidate_page.sha256, memory_sha256=mem_sha,
        requested_model=requested_model, pinned_returned_model=pinned_returned_model, atlas_config_id=atlas_config_id,
        memory_policy_version=packet.get("policy_version", MEMORY_POLICY_VERSION),
    )
    if reuse_cache:
        cached = find_reusable(key, mode, pinned_returned_model=pinned_returned_model, store_path=store_path)
        if cached is not None:
            return {**cached, "from_cache": True}

    request = build_contextual_request(packet, current_page.text, candidate_page.text, requested_model)
    try:
        outcome = dispatch(request)
    except Exception as e:  # noqa: BLE001 -- a dispatch that raises is a visible failure, never a mock answer
        outcome = ScoreOutcome("error", mode, requested_model, None, {}, None, 0.0, 0,
                               [f"dispatch raised {type(e).__name__}: {e}"], request.request_sha256())

    status, errors = outcome.status, list(outcome.errors)
    if outcome.mode != mode:
        status = "error"
        errors.append(f"dispatch ran in mode {outcome.mode!r} but mode {mode!r} was requested; not usable")
    if status == "ok" and pinned_returned_model and outcome.returned_model != pinned_returned_model:
        status = "invalid"
        errors.append(f"returned model {outcome.returned_model!r} != pinned {pinned_returned_model!r}; not pooled")

    record = {
        "schema": ASSESSMENT_SCHEMA,
        "assessment_id": f"ctx_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:10]}",
        "at": datetime.now(timezone.utc).isoformat(),
        "layer": LAYER,
        "mode": outcome.mode,
        "status": status,
        "cache_key": key,
        "memory_sha256": mem_sha,
        "memory_policy_version": packet.get("policy_version", MEMORY_POLICY_VERSION),
        "memory_source": packet.get("source"),
        "contextual_rubric_version": CONTEXTUAL_RUBRIC_VERSION,
        "atlas_config_id": atlas_config_id,
        "field": packet.get("field"),
        "current_id": current_page.id,
        "current_sha256": current_page.sha256,
        "candidate_id": candidate_page.id,
        "candidate_sha256": candidate_page.sha256,
        "requested_model": requested_model,
        "returned_model": outcome.returned_model,
        "pinned_returned_model": pinned_returned_model,
        "request_sha256": request.request_sha256(),
        "state": request.state,
        "questions": [q.to_dict() for q in request.questions],
        "answers": {qid: a.to_dict() for qid, a in outcome.answers.items()},
        "usage": outcome.usage,
        "elapsed_seconds": outcome.elapsed_seconds,
        "attempts": outcome.attempts,
        "errors": errors,
        "ledger_ids": list(outcome.ledger_ids),
    }
    _append(record, store_path)
    return {**record, "from_cache": False}
