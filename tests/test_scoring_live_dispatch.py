"""The real live dispatch code paths (scoring.make_live_dispatch, jev_client.run_choice),
exercised against a fake `typesafe_sdk` module -- never the network. These pin the
guarantees the budget accounting depends on: SDK hidden retries disabled, one ledger
reservation per HTTP attempt, at most two own retries, permanent errors not retried, a
refused reservation making no call, a failed call never becoming a success, and a returned
model other than the pinned one never being pooled."""
from __future__ import annotations

import sys
import types

import pytest

from gibsey_lab import jev_client, scoring
from gibsey_lab.config import Config
from gibsey_lab.jev_client import JevError
from gibsey_lab.scoring import ScoreQuestion, ScoreRequest

LEVELS = ("absent", "slight", "definite", "strong")


class FakeLedger:
    def __init__(self, allow: int = 99):
        self.allow = allow
        self.reserved: list[dict] = []
        self.settled: list[dict] = []

    def reserve(self, *, request_sha256, kind, est_input_tokens):
        if len(self.reserved) >= self.allow:
            return None
        self.reserved.append({"sha": request_sha256, "kind": kind, "est": est_input_tokens})
        return f"res-{len(self.reserved)}"

    def settle(self, reservation_id, *, ok, usage, returned_model, error):
        self.settled.append({"id": reservation_id, "ok": ok, "usage": usage, "model": returned_model, "error": error})


class FakeApiError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def install_fake_sdk(monkeypatch, responder):
    """responder(call_index, kwargs) -> response object or raises. Records every client."""
    calls: list[dict] = []
    clients: list[dict] = []

    class RetryPolicy:
        def __init__(self, **kw):
            self.kw = kw

    class _Question:
        def __init__(self, instructions=None, criteria=None):
            self.instructions, self.criteria = instructions, criteria

    class TypeSafeClient:
        def __init__(self, **kw):
            clients.append(kw)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def system_one(self, **kw):
            calls.append(kw)
            return responder(len(calls), kw)

    module = types.ModuleType("typesafe_sdk")
    module.RetryPolicy, module.TypeSafeClient, module.Score, module.Choice = RetryPolicy, TypeSafeClient, _Question, _Question
    monkeypatch.setitem(sys.modules, "typesafe_sdk", module)
    monkeypatch.setattr(scoring, "RETRY_SLEEP_SECONDS", 0.0)
    return calls, clients


def score_response(model="jev-1.13.0", peak=2):
    probabilities = {str(i): (1.0 if i == peak else 0.0) for i in range(4)}
    answer = {"type": "score", "score": float(peak), "confidence": 0.9, "probabilities": probabilities,
              "legend": {str(i): text for i, text in enumerate(LEVELS)}}
    return types.SimpleNamespace(model=model, usage={"input_tokens": 1234, "output_tokens": 10}, answers={"echo": answer})


def request() -> ScoreRequest:
    return ScoreRequest(
        kind="base_pair",
        state={"source_page": {"text": "the fox climbs"}, "destination_page": {"text": "the tower falls"}},
        questions=(ScoreQuestion("echo", "Does destination_page return to source_page?", LEVELS),),
        requested_model="jev-1.13.0",
    )


CFG = Config(model="jev-1.13.0", api_key="not-a-real-key")


def test_sdk_hidden_retries_are_disabled_and_one_attempt_is_one_reservation(monkeypatch):
    calls, clients = install_fake_sdk(monkeypatch, lambda n, kw: score_response())
    ledger = FakeLedger()
    outcome = scoring.make_live_dispatch(CFG, ledger)(request())

    assert outcome.status == "ok" and outcome.mode == "live" and outcome.attempts == 1
    assert len(calls) == 1 and len(ledger.reserved) == 1 and len(ledger.settled) == 1
    assert clients[0]["retry"].kw["max_retries"] == 0  # the SDK must never retry on its own
    assert ledger.settled[0]["ok"] is True and ledger.settled[0]["usage"]["input_tokens"] == 1234
    assert calls[0]["state"] == request().state and calls[0]["model"] == "jev-1.13.0"


def test_transient_failures_retry_at_most_twice_and_every_attempt_is_ledgered(monkeypatch):
    def responder(n, kw):
        raise FakeApiError(503)

    calls, _ = install_fake_sdk(monkeypatch, responder)
    ledger = FakeLedger()
    outcome = scoring.make_live_dispatch(CFG, ledger)(request())

    assert outcome.status == "error" and outcome.mode == "live" and outcome.answers == {}
    assert outcome.attempts == 3 == len(calls) == len(ledger.reserved) == len(ledger.settled)
    assert all(s["ok"] is False and s["usage"] is None for s in ledger.settled)
    assert len(outcome.ledger_ids) == 3


def test_a_retry_that_succeeds_counts_both_attempts(monkeypatch):
    def responder(n, kw):
        if n == 1:
            raise FakeApiError(529)
        return score_response()

    install_fake_sdk(monkeypatch, responder)
    ledger = FakeLedger()
    outcome = scoring.make_live_dispatch(CFG, ledger)(request())
    assert outcome.status == "ok" and outcome.attempts == 2 and len(ledger.reserved) == 2
    assert [s["ok"] for s in ledger.settled] == [False, True]


def test_permanent_errors_are_not_retried(monkeypatch):
    def responder(n, kw):
        raise FakeApiError(401)

    calls, _ = install_fake_sdk(monkeypatch, responder)
    ledger = FakeLedger()
    outcome = scoring.make_live_dispatch(CFG, ledger)(request())
    assert outcome.status == "error" and len(calls) == 1 and len(ledger.reserved) == 1


def test_a_refused_reservation_makes_no_network_call(monkeypatch):
    calls, _ = install_fake_sdk(monkeypatch, lambda n, kw: score_response())
    outcome = scoring.make_live_dispatch(CFG, FakeLedger(allow=0))(request())
    assert outcome.status == "budget_refused" and outcome.attempts == 0 and calls == []


def test_budget_running_out_mid_retry_is_an_error_not_a_success(monkeypatch):
    def responder(n, kw):
        raise FakeApiError(503)

    calls, _ = install_fake_sdk(monkeypatch, responder)
    outcome = scoring.make_live_dispatch(CFG, FakeLedger(allow=1))(request())
    assert outcome.status == "error" and outcome.attempts == 1 and len(calls) == 1


def test_a_returned_model_other_than_the_pin_is_invalid_not_pooled(monkeypatch):
    install_fake_sdk(monkeypatch, lambda n, kw: score_response(model="jev-1.14.0"))
    outcome = scoring.make_live_dispatch(CFG, FakeLedger(), expected_returned_model="jev-1.13.0")(request())
    assert outcome.status == "invalid" and outcome.returned_model == "jev-1.14.0"
    assert any("pinned" in e for e in outcome.errors)


def test_missing_credentials_is_a_visible_error_never_a_mock(monkeypatch):
    calls, _ = install_fake_sdk(monkeypatch, lambda n, kw: score_response())
    outcome = scoring.make_live_dispatch(Config(model="jev-1.13.0", api_key=None), FakeLedger())(request())
    assert outcome.status == "error" and outcome.mode == "live" and calls == []


def test_a_malformed_answer_is_invalid_while_a_low_score_is_valid(monkeypatch):
    def malformed(n, kw):
        response = score_response()
        response.answers["echo"]["probabilities"] = {"0": 0.5, "1": 0.1}  # wrong keys, does not sum to 1
        return response

    install_fake_sdk(monkeypatch, malformed)
    assert scoring.make_live_dispatch(CFG, FakeLedger())(request()).status == "invalid"

    install_fake_sdk(monkeypatch, lambda n, kw: score_response(peak=0))
    low = scoring.make_live_dispatch(CFG, FakeLedger())(request())
    assert low.status == "ok" and low.answers["echo"].score == 0.0 and low.answers["echo"].valid


# ---------------------------------------------------------------- operator Choice path


def choice_response():
    answer = types.SimpleNamespace(choice="P2", probabilities={"P2": 0.7, "NONE": 0.3}, confidence=0.7)
    return types.SimpleNamespace(model="jev-1.13.0", usage={"input_tokens": 900, "output_tokens": 5}, answers={"destination": answer})


def test_choice_call_disables_sdk_retries_and_is_ledgered(monkeypatch):
    calls, clients = install_fake_sdk(monkeypatch, lambda n, kw: choice_response())
    ledger = FakeLedger()
    result = jev_client.run_choice(CFG, state="source", instructions="pick", criteria={"P2": "text", "NONE": "none"}, ledger=ledger)

    assert result.choice == "P2" and result.live is True
    assert clients[0]["retry"].kw["max_retries"] == 0
    assert len(calls) == 1 and ledger.reserved[0]["kind"] == "operator_choice" and ledger.settled[0]["ok"] is True


def test_choice_call_failure_is_settled_as_failed_and_raises(monkeypatch):
    def responder(n, kw):
        raise FakeApiError(503)

    calls, _ = install_fake_sdk(monkeypatch, responder)
    ledger = FakeLedger()
    with pytest.raises(JevError):
        jev_client.run_choice(CFG, state="s", instructions="i", criteria={"P2": "t", "NONE": "n"}, ledger=ledger)
    assert len(calls) == 1 and ledger.settled == [
        {"id": "res-1", "ok": False, "usage": None, "model": None, "error": "FakeApiError: HTTP 503"}
    ]


def test_choice_call_refused_by_the_ledger_makes_no_network_call(monkeypatch):
    calls, _ = install_fake_sdk(monkeypatch, lambda n, kw: choice_response())
    with pytest.raises(JevError, match="refused"):
        jev_client.run_choice(CFG, state="s", instructions="i", criteria={"P2": "t", "NONE": "n"}, ledger=FakeLedger(allow=0))
    assert calls == []
