"""Shared Score-request layer for the relationship atlas and contextual assessments.

One `ScoreRequest` is one provider request: a JSON `state` plus several independent
TypeSafe Score questions. Questions in one request never see each other's answers (per
the TypeSafe docs each is evaluated separately against the state), so batching is only a
transport convenience -- every question's instructions must identify the evaluated
endpoints by the role keys present in `state`.

Guarantees:
- `mode` ("live" | "mock") is stamped by the dispatch that actually ran, never by the
  caller, and a failed live call is returned as status="error" -- it is never replaced by
  a mock answer.
- The live dispatch disables the SDK's own hidden retries (typesafe-sdk defaults to 2) and
  performs at most MAX_RETRIES_PER_REQUEST retries itself, reserving budget in the ledger
  before *every* attempt, so the ledger's attempt count is the real number of HTTP
  request attempts.
- Nothing here reads or logs the API key; the SDK reads TYPESAFE_API_KEY from the
  environment after config.load_config() has loaded it.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol

from .config import Config

MAX_RETRIES_PER_REQUEST = 2
RETRY_SLEEP_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 30.0
MOCK_MODEL = "mock-lexical-overlap-v1"

# Conservative pre-dispatch estimate: the docs do not say whether `state` is billed once
# per request or once per question, so assume once per question, at ~3 chars/token.
# Reconciled against reported usage when the attempt settles.
_CHARS_PER_TOKEN = 3.0


@dataclass(frozen=True)
class ScoreQuestion:
    qid: str
    instructions: str
    levels: tuple[str, ...]  # ordered low -> high; position is the level number

    def to_dict(self) -> dict:
        return {"qid": self.qid, "instructions": self.instructions, "levels": list(self.levels)}


@dataclass(frozen=True)
class ScoreRequest:
    kind: str  # "base_pair" | "contextual"
    state: dict
    questions: tuple[ScoreQuestion, ...]
    requested_model: str

    def canonical(self) -> dict:
        return {
            "kind": self.kind,
            "state": self.state,
            "questions": [q.to_dict() for q in self.questions],
            "requested_model": self.requested_model,
        }

    def request_sha256(self) -> str:
        blob = json.dumps(self.canonical(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScoreAnswer:
    qid: str
    score: float | None
    max_level: int
    confidence: float | None
    probabilities: dict[str, float]
    legend: dict[str, str]
    valid: bool
    problems: list[str] = field(default_factory=list)

    @property
    def score_norm(self) -> float | None:
        if self.score is None or self.max_level <= 0:
            return None
        return self.score / self.max_level

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score_norm"] = self.score_norm
        return d


@dataclass(frozen=True)
class ScoreOutcome:
    status: str  # "ok" | "invalid" | "error" | "budget_refused"
    mode: str  # "live" | "mock"
    requested_model: str
    returned_model: str | None
    answers: dict[str, ScoreAnswer]
    usage: dict | None
    elapsed_seconds: float
    attempts: int
    errors: list[str]
    request_sha256: str
    ledger_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["answers"] = {qid: a.to_dict() for qid, a in self.answers.items()}
        return d


Dispatch = Callable[[ScoreRequest], ScoreOutcome]


class BudgetLedger(Protocol):
    """Implemented by gibsey_lab.atlas.ledger. One reservation per HTTP attempt."""

    def reserve(self, *, request_sha256: str, kind: str, est_input_tokens: int) -> str | None:
        """Returns a reservation id, or None if any cap would be exceeded."""

    def settle(
        self, reservation_id: str, *, ok: bool, usage: dict | None, returned_model: str | None, error: str | None
    ) -> None: ...


def estimate_input_tokens(request: ScoreRequest) -> int:
    state_chars = len(json.dumps(request.state, ensure_ascii=False))
    question_chars = sum(len(q.instructions) + sum(len(level) for level in q.levels) for q in request.questions)
    return int((state_chars * len(request.questions) + question_chars) / _CHARS_PER_TOKEN) + 64


def validate_answer(question: ScoreQuestion, raw: dict | None) -> ScoreAnswer:
    """Structural validation of one Score answer. A low score is a valid answer; only a
    malformed one is invalid."""
    max_level = len(question.levels) - 1
    if raw is None:
        return ScoreAnswer(question.qid, None, max_level, None, {}, {}, False, ["answer missing from response"])

    problems: list[str] = []
    score = raw.get("score")
    confidence = raw.get("confidence")
    probabilities = {str(k): v for k, v in (raw.get("probabilities") or {}).items()}
    legend = {str(k): v for k, v in (raw.get("legend") or {}).items()}
    expected_keys = [str(i) for i in range(len(question.levels))]

    if raw.get("type") not in (None, "score"):
        problems.append(f"answer type is {raw.get('type')!r}, not 'score'")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        problems.append(f"score is not numeric: {score!r}")
        score = None
    elif not (-1e-6 <= score <= max_level + 1e-6):
        problems.append(f"score {score} outside 0..{max_level}")
    if sorted(probabilities) != sorted(expected_keys):
        problems.append(f"probability keys {sorted(probabilities)} != levels {expected_keys}")
    elif any(not isinstance(v, (int, float)) or v < -1e-6 for v in probabilities.values()):
        problems.append("non-numeric or negative probability")
    else:
        total = sum(probabilities.values())
        if abs(total - 1.0) > 0.03:
            problems.append(f"probabilities sum to {total:.4f}")
        elif score is not None:
            mean = sum(int(k) * v for k, v in probabilities.items())
            if abs(mean - score) > 0.06 * max(1, max_level):
                problems.append(f"score {score} disagrees with distribution mean {mean:.3f}")
    if legend:
        for key, level_text in zip(expected_keys, question.levels):
            if legend.get(key) != level_text:
                problems.append(f"legend level {key} does not match the requested rubric text")
                break
    if confidence is not None and not (isinstance(confidence, (int, float)) and -1e-6 <= confidence <= 1 + 1e-6):
        problems.append(f"confidence out of range: {confidence!r}")

    return ScoreAnswer(
        qid=question.qid,
        score=None if score is None else float(score),
        max_level=max_level,
        confidence=None if confidence is None else float(confidence),
        probabilities={k: float(v) for k, v in probabilities.items() if isinstance(v, (int, float))},
        legend={k: v for k, v in legend.items() if isinstance(v, str)},
        valid=not problems,
        problems=problems,
    )


def _outcome_from_raw_answers(
    request: ScoreRequest, raw_answers: dict, *, mode: str, returned_model: str | None, usage: dict | None,
    elapsed: float, attempts: int, errors: list[str], ledger_ids: list[str], expected_returned_model: str | None = None,
) -> ScoreOutcome:
    answers = {q.qid: validate_answer(q, raw_answers.get(q.qid)) for q in request.questions}
    errors = list(errors)
    status = "ok" if all(a.valid for a in answers.values()) else "invalid"
    if expected_returned_model and returned_model != expected_returned_model:
        status = "invalid"
        errors.append(f"returned model {returned_model!r} != pinned {expected_returned_model!r}; not pooled")
    return ScoreOutcome(
        status=status, mode=mode, requested_model=request.requested_model, returned_model=returned_model,
        answers=answers, usage=usage, elapsed_seconds=elapsed, attempts=attempts, errors=errors,
        request_sha256=request.request_sha256(), ledger_ids=ledger_ids,
    )


# --------------------------------------------------------------------------- mock

_WORD = re.compile(r"[A-Za-z']+")


def _texts(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [t for v in node.values() for t in _texts(v)]
    if isinstance(node, list):
        return [t for v in node for t in _texts(v)]
    return []


def mock_dispatch(request: ScoreRequest) -> ScoreOutcome:
    """Deterministic offline stand-in. Level = a hash of (request, question) blended with
    lexical overlap between the state's texts -- stable across runs, sensitive to any
    change in the supplied state, and not a literary judgment. Always mode="mock"."""
    texts = _texts(request.state)
    token_sets = [{w.lower() for w in _WORD.findall(t)} for t in texts if t.strip()]
    overlap = 0.0
    if len(token_sets) >= 2:
        first, last = token_sets[0], token_sets[-1]
        overlap = len(first & last) / max(1, len(first | last))

    raw: dict[str, dict] = {}
    for q in request.questions:
        n = len(q.levels)
        digest = hashlib.sha256(f"{request.request_sha256()}:{q.qid}".encode()).digest()
        jitter = digest[0] / 255.0
        position = min(0.999, max(0.0, 0.6 * jitter + 1.6 * overlap))
        peak = int(position * n)
        second = min(n - 1, peak + 1) if digest[1] % 2 else max(0, peak - 1)
        probabilities = {str(i): 0.0 for i in range(n)}
        probabilities[str(peak)] += 0.7
        probabilities[str(second)] += 0.3
        raw[q.qid] = {
            "type": "score",
            "score": sum(int(k) * v for k, v in probabilities.items()),
            "confidence": 0.5,
            "probabilities": probabilities,
            "legend": {str(i): text for i, text in enumerate(q.levels)},
        }
    return _outcome_from_raw_answers(
        request, raw, mode="mock", returned_model=MOCK_MODEL, usage=None, elapsed=0.0, attempts=0, errors=[],
        ledger_ids=[],
    )


# --------------------------------------------------------------------------- live


def _answer_to_dict(answer) -> dict | None:
    if answer is None:
        return None
    if isinstance(answer, dict):
        return answer
    if hasattr(answer, "model_dump"):
        return answer.model_dump()
    return {k: getattr(answer, k, None) for k in ("type", "score", "confidence", "probabilities", "legend")}


def _usage_to_dict(usage) -> dict | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return dict(usage)
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return {k: getattr(usage, k) for k in ("input_tokens", "output_tokens") if hasattr(usage, k)} or None


def _is_permanent(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    return status in (400, 401, 403, 404, 422)


def make_live_dispatch(cfg: Config, ledger: BudgetLedger, *, expected_returned_model: str | None = None) -> Dispatch:
    """Lead-only wiring. Each HTTP attempt reserves ledger capacity first; a refused
    reservation ends the request as status="budget_refused" without any network call."""

    def dispatch(request: ScoreRequest) -> ScoreOutcome:
        sha = request.request_sha256()
        if not cfg.has_live_credentials:
            return ScoreOutcome("error", "live", request.requested_model, None, {}, None, 0.0, 0,
                                ["TYPESAFE_API_KEY is not set; cannot make a live Jev call"], sha)
        try:
            from typesafe_sdk import RetryPolicy, Score, TypeSafeClient
        except ImportError as e:
            return ScoreOutcome("error", "live", request.requested_model, None, {}, None, 0.0, 0,
                                [f"typesafe-sdk is not installed: {e}"], sha)

        questions = {q.qid: Score(instructions=q.instructions, criteria=list(q.levels)) for q in request.questions}
        estimate = estimate_input_tokens(request)
        errors: list[str] = []
        ledger_ids: list[str] = []
        attempts = 0
        start = time.monotonic()

        for attempt in range(MAX_RETRIES_PER_REQUEST + 1):
            reservation = ledger.reserve(request_sha256=sha, kind=request.kind, est_input_tokens=estimate)
            if reservation is None:
                errors.append("budget ledger refused the reservation (a cap would be exceeded)")
                status = "budget_refused" if attempts == 0 else "error"
                return ScoreOutcome(status, "live", request.requested_model, None, {}, None,
                                    time.monotonic() - start, attempts, errors, sha, ledger_ids)
            ledger_ids.append(reservation)
            attempts += 1
            try:
                with TypeSafeClient(
                    retry=RetryPolicy(max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)
                ) as client:
                    response = client.system_one(state=request.state, model=request.requested_model, questions=questions)
            except Exception as e:  # noqa: BLE001 -- SDK error types vary; all are visible failures
                message = f"{type(e).__name__}: {e}"
                errors.append(message)
                ledger.settle(reservation, ok=False, usage=None, returned_model=None, error=message)
                if _is_permanent(e) or attempt == MAX_RETRIES_PER_REQUEST:
                    break
                time.sleep(RETRY_SLEEP_SECONDS * (attempt + 1))
                continue

            usage = _usage_to_dict(getattr(response, "usage", None))
            returned_model = getattr(response, "model", None)
            ledger.settle(reservation, ok=True, usage=usage, returned_model=returned_model, error=None)
            answers = getattr(response, "answers", None) or {}
            raw = {q.qid: _answer_to_dict(answers.get(q.qid) if hasattr(answers, "get") else None) for q in request.questions}
            return _outcome_from_raw_answers(
                request, raw, mode="live", returned_model=returned_model, usage=usage,
                elapsed=time.monotonic() - start, attempts=attempts, errors=errors, ledger_ids=ledger_ids,
                expected_returned_model=expected_returned_model,
            )

        return ScoreOutcome("error", "live", request.requested_model, None, {}, None,
                            time.monotonic() - start, attempts, errors, sha, ledger_ids)

    return dispatch
