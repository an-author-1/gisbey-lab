"""Isolated reader instance for browser acceptance.

Session, outcome, option/offer-set, run and contextual stores all live in a temp dir, so
the user's real reading session is never touched. The REAL live atlas is read (read-only)
so the options shown are the ones the real reader shows. Every provider behaviour here is
a clearly named MOCK, switchable at runtime:

    POST /__test/provider {"mode": "ok" | "slow" | "error" | "timeout" | "weak" | "pick_none"}
    GET  /__test/counters

Nothing in this file can make a live call: the contextual dispatch is always one of the
mocks below, and the single-pick Choice path is forced to the mock client.
"""
from __future__ import annotations

import dataclasses
import sys
import threading
import time
from pathlib import Path

from gibsey_lab import mock_client, runner, scoring
from gibsey_lab.memory import contextual, offers
from gibsey_lab.reader import server
from gibsey_lab.results import ChoiceResult
from gibsey_lab.scoring import ScoreOutcome

STATE = {"mode": "ok"}
COUNTERS = {"contextual_dispatches": 0, "single_pick_dispatches": 0}
_LOCK = threading.Lock()


def _error(request, message: str) -> ScoreOutcome:
    return ScoreOutcome("error", "mock", request.requested_model, None, {}, None, 0.0, 1, [message],
                        request.request_sha256())


def mock_contextual_dispatch(request):
    with _LOCK:
        COUNTERS["contextual_dispatches"] += 1
    mode = STATE["mode"]
    if mode == "slow":
        time.sleep(2.0)
    if mode == "timeout":
        time.sleep(2.5)
        return _error(request, "MOCK TypeSafeAPITimeoutError: request exceeded its timeout")
    if mode == "error":
        return _error(request, "MOCK TypeSafeAPIError: HTTP 529 service overloaded")
    outcome = _as_pinned(scoring.mock_dispatch(request))
    if mode == "weak":  # a contextual "abstention": every answer at the lowest level
        raw = {q.qid: {"type": "score", "score": 0.0, "confidence": 0.9,
                       "probabilities": {str(i): (1.0 if i == 0 else 0.0) for i in range(len(q.levels))},
                       "legend": {str(i): t for i, t in enumerate(q.levels)}} for q in request.questions}
        outcome = scoring._outcome_from_raw_answers(  # noqa: SLF001 -- test harness
            request, raw, mode="mock", returned_model=scoring.MOCK_MODEL, usage=None, elapsed=0.0,
            attempts=0, errors=[], ledger_ids=[])
        outcome = _as_pinned(outcome)
    return outcome


def _as_pinned(outcome: ScoreOutcome) -> ScoreOutcome:
    """The option sets come from the real live atlas, whose frozen config pins a returned
    model; the reader (correctly) rejects any answer from another model as "not pooled".
    So that success paths can be exercised, this MOCK reports the pinned id. It is still
    stamped mode="mock" and is only ever written to this instance's temp stores."""
    from gibsey_lab.atlas import api as atlas_api

    pinned = atlas_api.active_config("live").get("pinned_returned_model")
    return dataclasses.replace(outcome, returned_model=pinned) if pinned else outcome


_real_mock_choice = mock_client.run_choice_mock


def mock_choice(**kw):
    with _LOCK:
        COUNTERS["single_pick_dispatches"] += 1
    if STATE["mode"] == "slow":
        time.sleep(2.0)
    if STATE["mode"] == "pick_none":
        order = kw["option_order"]
        probabilities = {k: (0.6 if k == "NONE" else 0.4 / (len(order) - 1)) for k in order}
        return ChoiceResult(requested_model=kw["model"], returned_model="mock-lexical-overlap-v1", choice="NONE",
                            confidence=0.6, probabilities=probabilities, usage={}, elapsed_seconds=0.0, live=False)
    return _real_mock_choice(**kw)


def main() -> None:
    base, port = Path(sys.argv[1]), int(sys.argv[2])
    (base / "data").mkdir(parents=True, exist_ok=True)
    (base / "runs").mkdir(parents=True, exist_ok=True)
    server.DATA_DIR = base / "data"
    server.RUNS_DIR = base / "runs"
    server.SESSION_LOG_PATH = base / "data" / "session_log.jsonl"
    server.CORE_DIR = base / "data" / "core"  # the Core journals: never the real data/core
    contextual.ASSESSMENTS_PATH = base / "data" / "contextual_assessments.jsonl"
    offers.OFFER_SETS_PATH = base / "data" / "offer_sets.jsonl"
    server.OFFER_DISPATCH_FACTORY = lambda: (mock_contextual_dispatch, "mock", "mock-requested-model")

    # The single-pick research action: always the mock Choice client, never the network.
    mock_client.run_choice_mock = mock_choice
    real_run_case = runner.run_case
    server.run_case = lambda packet, cfg, *, mock=False, **kw: real_run_case(packet, cfg, mock=True, **kw)

    def set_provider(body: dict) -> dict:
        STATE["mode"] = body.get("mode", "ok")
        return {"mode": STATE["mode"]}

    server.POST_ROUTES["/__test/provider"] = set_provider
    server.GET_ROUTES["/__test/counters"] = lambda _q: dict(COUNTERS, mode=STATE["mode"])
    server.run(port=port, open_browser=False)


if __name__ == "__main__":
    main()
