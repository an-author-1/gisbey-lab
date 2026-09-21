"""Shared synthetic fixtures for the memory tests (no tests here). Nothing touches the real
corpus, data/, runs/, or any provider: fields are synthetic, stores live under tmp_path."""
from __future__ import annotations

import hashlib
from pathlib import Path

from gibsey_lab.corpus import Page
from gibsey_lab.fields import Field
from gibsey_lab.memory import contextual
from gibsey_lab.memory.shortlist import ALL_DIMENSIONS
from gibsey_lab.scoring import ScoreAnswer, ScoreOutcome, ScoreRequest, validate_answer

FAKE_MODEL = "fake-returned-model"


def make_field(prefixes: dict[str, int] | None = None) -> Field:
    prefixes = prefixes or {"PR": 8, "LF": 6, "P": 4}
    manifest = {}
    for prefix, count in prefixes.items():
        for n in range(1, count + 1):
            pid = f"{prefix}{n}"
            text = f"Body of {prefix.lower()} page number {n}: <b>distinct</b> prose token tok{prefix.lower()}{n} & more."
            manifest[pid] = Page(id=pid, path=Path(f"/nonexistent/{pid}.md"), text=text,
                                 sha256=hashlib.sha256(text.encode()).hexdigest(), order=n)
    return Field(id="full-41", label="synthetic", manifest=manifest)


def ev(event: str, page_id: str | None = None, **fields) -> dict:
    record = {"at": "2026-09-20T00:00:00+00:00", "event": event, "field": "full-41", **fields}
    if page_id is not None:
        record["page_id"] = page_id
    return record


def make_rows(field: Field, source: str, scores: dict[str, dict] | None = None, *, default_status: str = "complete",
              statuses: dict[str, str] | None = None) -> list[dict]:
    """One row per other page. `scores[pid]` overrides dimension score_norms; everything
    else defaults to a weak-but-valid profile (all relations absent)."""
    scores, statuses = scores or {}, statuses or {}
    neighbors = set(field.neighbors_of(source).values())
    rows = []
    for pid in field.candidate_ids_for(source):
        status = statuses.get(pid, default_status)
        row = {"source_id": source, "destination_id": pid, "status": status, "is_authored_neighbor": pid in neighbors}
        if status == "complete":
            norms = {"direct_q_fit": 0.67, "redundancy": 0.0, "missing_context": 0.0, **scores.get(pid, {})}
            row["dimensions"] = {
                dim: {"score": norms.get(dim, 0.0) * 3, "score_norm": norms.get(dim, 0.0), "max_level": 3,
                      "confidence": 0.8, "valid": True}
                for dim in ALL_DIMENSIONS
            }
            row["assessment_id"] = f"atlas_{source}_{pid}"
            row["destination_sha256"] = field.manifest[pid].sha256
        rows.append(row)
    return rows


def atlas_config(mode: str) -> dict:
    return {"config_id": f"cfg-{mode}", "rubric_version": "atlas-rubric-test"}


class ScriptedDispatch:
    """Records every request. `script(request)` returns {qid: score 0..3}, or "error", or
    raises. Default: every candidate works (3), grounded (2), no repetition (0)."""

    def __init__(self, script=None, mode: str = "mock"):
        self.script = script or (lambda request: {"works_after_history": 3.0, "grounded_reading_effect": 2.0,
                                                  "repeats_recent_reading": 0.0})
        self.mode = mode
        self.requests: list[ScoreRequest] = []

    def __call__(self, request: ScoreRequest) -> ScoreOutcome:
        self.requests.append(request)
        scores = self.script(request)
        sha = request.request_sha256()
        if scores == "error":
            return ScoreOutcome("error", self.mode, request.requested_model, None, {}, None, 0.0, 1,
                                ["simulated transport failure"], sha)
        answers = {
            qid: ScoreAnswer(qid=qid, score=float(scores[qid]), max_level=3, confidence=0.75,
                             probabilities={}, legend={}, valid=True)
            for qid in contextual.QUESTION_IDS
        }
        return ScoreOutcome("ok", self.mode, request.requested_model, FAKE_MODEL, answers,
                            {"input_tokens": 100, "output_tokens": 10}, 0.01, 1, [], sha)


def by_candidate(field: Field, table: dict[str, object], default=None):
    """Script keyed by candidate page id (resolved from the candidate text -- the request
    itself never carries ids)."""
    by_text = {field.manifest[pid].text: value for pid, value in table.items()}

    def script(request: ScoreRequest):
        value = by_text.get(request.state["candidate_destination"]["text"], default)
        if value is None:
            return {"works_after_history": 3.0, "grounded_reading_effect": 2.0, "repeats_recent_reading": 0.0}
        if isinstance(value, tuple):
            return dict(zip(contextual.QUESTION_IDS, value))
        return value

    return script


def leveled_outcome(request: ScoreRequest, levels: dict[str, int], *, mode: str = "mock",
                    returned_model: str = FAKE_MODEL) -> ScoreOutcome:
    """A fully valid outcome (one-hot distribution, matching legend) for ANY request --
    base-pair or contextual -- with the given integer level per question id (default 0)."""
    answers = {}
    for q in request.questions:
        level = int(levels.get(q.qid, 0))
        raw = {"type": "score", "score": float(level), "confidence": 0.9,
               "probabilities": {str(i): 1.0 if i == level else 0.0 for i in range(len(q.levels))},
               "legend": {str(i): text for i, text in enumerate(q.levels)}}
        answers[q.qid] = validate_answer(q, raw)
    assert all(a.valid for a in answers.values())
    return ScoreOutcome("ok", mode, request.requested_model, returned_model, answers, None, 0.0, 0, [],
                        request.request_sha256())
