from __future__ import annotations

import inspect
import json
import threading
from datetime import datetime, timedelta, timezone

from gibsey_lab import scoring
from gibsey_lab.atlas import ledger as ledger_module
from gibsey_lab.atlas.ledger import Ledger

from test_atlas_support import atlas_env  # noqa: F401


def _reserve(ledger: Ledger, est: int = 1000, sha: str = "sha-a"):
    return ledger.reserve(request_sha256=sha, kind="base_pair", est_input_tokens=est)


def _settle_ok(ledger: Ledger, rid: str, tokens: int = 800):
    ledger.settle(rid, ok=True, usage={"input_tokens": tokens, "output_tokens": 50}, returned_model="jev-t", error=None)


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _advance_clock(monkeypatch, seconds: float) -> None:
    later = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    monkeypatch.setattr(ledger_module, "_utcnow", lambda: later)


def test_caps_are_the_milestone_limits_and_cannot_be_loosened(atlas_env):
    assert (ledger_module.MAX_ATTEMPTS, ledger_module.MAX_INPUT_TOKENS, ledger_module.MAX_IN_FLIGHT) == (2000, 10_000_000, 2)
    loose = Ledger(max_attempts=10**9, max_input_tokens=10**12, max_in_flight=50)
    assert loose.summary()["caps"] == {"max_attempts": 2000, "max_input_tokens": 10_000_000, "max_in_flight": 2}
    assert Ledger().path == ledger_module.LEDGER_PATH
    assert not ledger_module.LEDGER_PATH.exists()  # constructing a ledger writes nothing


def test_implements_the_scoring_protocol_signatures():
    for name in ("reserve", "settle"):
        ours = inspect.signature(getattr(Ledger, name))
        theirs = inspect.signature(getattr(scoring.BudgetLedger, name))
        assert [(p.name, p.kind) for p in ours.parameters.values()] == [(p.name, p.kind) for p in theirs.parameters.values()]


def test_attempt_cap_counts_every_attempt_including_failed_retries(atlas_env):
    ledger = Ledger(max_attempts=3)
    first = _reserve(ledger)
    ledger.settle(first, ok=False, usage=None, returned_model=None, error="Timeout")  # attempt 1 fails
    retry = _reserve(ledger)
    ledger.settle(retry, ok=False, usage=None, returned_model=None, error="Timeout")  # its retry fails too
    _settle_ok(ledger, _reserve(ledger))
    assert _reserve(ledger) is None
    summary = ledger.summary()
    assert (summary["attempts"], summary["settled_ok"], summary["settled_failed"]) == (3, 1, 2)
    assert summary["remaining_attempts"] == 0
    assert [line["event"] for line in _lines(ledger.path)].count("refuse") == 1


def test_token_cap_uses_reported_usage_and_charges_the_estimate_when_usage_is_unknown(atlas_env):
    ledger = Ledger(max_input_tokens=5000)
    _settle_ok(ledger, _reserve(ledger, est=3000), tokens=1000)  # reconciled down to reported usage
    assert ledger.summary()["tokens_total"] == 1000

    failed = _reserve(ledger, est=1500)
    ledger.settle(failed, ok=False, usage=None, returned_model=None, error="ConnectionError")
    no_usage = _reserve(ledger, est=1500)
    ledger.settle(no_usage, ok=True, usage={"output_tokens": 5}, returned_model="jev-t", error=None)

    summary = ledger.summary()
    assert summary["tokens_reported"] == 1000 and summary["tokens_estimated_unknown"] == 3000
    assert summary["tokens_total"] == 4000 and summary["remaining_input_tokens"] == 1000
    settles = [line for line in _lines(ledger.path) if line["event"] == "settle"]
    assert [s["usage_unknown"] for s in settles] == [False, True, True]
    assert [s["charged_input_tokens"] for s in settles] == [1000, 1500, 1500]

    assert _reserve(ledger, est=1001) is None  # would exceed the token cap
    assert _reserve(ledger, est=1000) is not None  # exactly fits


def test_in_flight_cap_refuses_without_blocking(atlas_env):
    ledger = Ledger()
    a, b = _reserve(ledger), _reserve(ledger)
    assert a and b and ledger.summary()["in_flight"] == 2
    assert _reserve(ledger) is None
    _settle_ok(ledger, a)
    assert _reserve(ledger) is not None


def test_restart_does_not_reset_the_allowance(atlas_env):
    first = Ledger(max_attempts=4)
    for _ in range(3):
        _settle_ok(first, _reserve(first), tokens=700)
    restarted = Ledger(max_attempts=4)
    summary = restarted.summary()
    assert (summary["attempts"], summary["tokens_reported"], summary["remaining_attempts"]) == (3, 2100, 1)
    assert summary["returned_models"] == ["jev-t"]
    _settle_ok(restarted, _reserve(restarted))
    assert _reserve(restarted) is None
    assert Ledger(max_attempts=4).summary()["attempts"] == 4


def test_reservations_left_by_a_dead_process_count_as_spent_at_their_estimate(atlas_env, monkeypatch):
    dead = Ledger(max_attempts=3, max_input_tokens=10_000)
    _reserve(dead, est=4000)
    _reserve(dead, est=4000)  # the process "dies" here: neither is ever settled
    del dead

    survivor = Ledger(max_attempts=3, max_input_tokens=10_000)
    summary = survivor.summary()
    assert (summary["attempts"], summary["unsettled"], summary["tokens_unsettled_estimate"]) == (2, 2, 8000)
    # Inside the staleness window they may still be running somewhere, so they block ...
    assert summary["in_flight"] == 2 and _reserve(survivor, est=1) is None

    # ... and once older than the window they are dead: still spent, no longer blocking.
    _advance_clock(monkeypatch, ledger_module.IN_FLIGHT_STALE_SECONDS + 1)
    summary = survivor.summary()
    assert (summary["attempts"], summary["tokens_unsettled_estimate"], summary["in_flight"]) == (2, 8000, 0)
    assert _reserve(survivor, est=2001) is None  # 8000 + 2001 > 10000
    assert _reserve(survivor, est=2000) is not None
    assert _reserve(survivor, est=0) is None  # 3 attempts used


def test_two_ledger_instances_on_one_file_share_one_in_flight_cap(atlas_env, monkeypatch):
    assert ledger_module.IN_FLIGHT_STALE_SECONDS == 180
    a, b = Ledger(), Ledger()  # e.g. the atlas build and the reader server on one ledger file
    first, second = _reserve(a), _reserve(b)
    assert first and second
    assert _reserve(a) is None and _reserve(b) is None  # 2 in flight across BOTH, not 2 each
    assert a.summary()["in_flight"] == b.summary()["in_flight"] == 2
    assert "in-flight cap" in _lines(a.path)[-1]["reason"]

    _settle_ok(b, first)  # settled through the other instance: capacity frees for everyone
    third = _reserve(a)
    assert third and _reserve(b) is None

    _advance_clock(monkeypatch, ledger_module.IN_FLIGHT_STALE_SECONDS + 1)
    assert b.summary()["in_flight"] == 0 and _reserve(b) is not None  # the two stale ones no longer block
    assert b.summary()["attempts"] == 4  # but every one of them is still charged


def test_a_torn_trailing_line_cannot_swallow_the_next_reservation(atlas_env):
    ledger = Ledger(max_attempts=10)
    _settle_ok(ledger, _reserve(ledger), tokens=100)
    with open(ledger.path, "a") as f:
        f.write('{"schema": "atlas-ledger/1", "event": "reserve", "reservation_id": "res-torn", "est_inp')  # no newline

    rid = _reserve(ledger, est=700)  # previously: appended onto the fragment and lost
    assert rid is not None
    _settle_ok(ledger, rid, tokens=650)  # previously: KeyError after the HTTP call had already happened
    assert all(line.endswith("}") for line in ledger.path.read_text().splitlines() if '"est_inp' not in line)

    for view in (ledger.summary(), Ledger(max_attempts=10).summary()):  # same totals live and after a restart
        assert view["corrupt_lines_charged_as_attempts"] == 1
        assert (view["attempts"], view["settled_ok"], view["tokens_reported"], view["unsettled"]) == (3, 2, 750, 0)


def test_settling_an_unknown_reservation_is_recorded_and_never_raises(atlas_env):
    ledger = Ledger(max_attempts=5)
    ledger.settle("res-lost", ok=True, usage={"input_tokens": 900}, returned_model="jev-t", error=None)
    ledger.settle("res-lost-2", ok=False, usage=None, returned_model=None, error="Timeout")
    ledger.release("res-never-seen")
    lines = _lines(ledger.path)
    assert [line["event"] for line in lines] == ["settle", "settle", "release"]
    assert all(line["unknown_reservation"] is True for line in lines)
    assert lines[1]["usage_unknown"] is True

    for view in (ledger.summary(), Ledger(max_attempts=5).summary()):  # the attempts happened: they are charged
        assert (view["attempts"], view["settled_ok"], view["settled_failed"], view["tokens_reported"]) == (2, 1, 1, 900)
        assert view["in_flight"] == 0 and view["returned_models"] == ["jev-t"]
    ledger.settle("res-lost", ok=True, usage={"input_tokens": 5}, returned_model="jev-t", error=None)  # still idempotent
    assert ledger.summary()["tokens_reported"] == 900


def test_two_ledgers_on_one_file_share_one_allowance(atlas_env):
    a, b = Ledger(max_attempts=3), Ledger(max_attempts=3)
    _settle_ok(a, _reserve(a))
    _settle_ok(b, _reserve(b))
    _settle_ok(a, _reserve(a))
    assert _reserve(b) is None and _reserve(a) is None


def test_settle_is_idempotent_and_release_frees_an_unsent_attempt(atlas_env):
    ledger = Ledger(max_attempts=2)
    rid = _reserve(ledger)
    _settle_ok(ledger, rid, tokens=500)
    _settle_ok(ledger, rid, tokens=99999)  # ignored: never charged twice
    assert ledger.summary()["tokens_total"] == 500
    unsent = _reserve(ledger)
    ledger.release(unsent)
    assert ledger.summary()["attempts"] == 1 and _reserve(ledger) is not None


def test_unreadable_history_is_charged_not_forgiven(atlas_env):
    ledger = Ledger(max_attempts=3)
    _settle_ok(ledger, _reserve(ledger))
    with open(ledger.path, "a") as f:
        f.write("{this is not json\n")
    reopened = Ledger(max_attempts=3)
    assert reopened.summary()["attempts"] == 2 and reopened.summary()["corrupt_lines_charged_as_attempts"] == 1


def test_threaded_reservations_never_exceed_the_attempt_cap(atlas_env):
    ledger = Ledger(max_attempts=25)
    granted = []

    def worker():
        for _ in range(300):  # in-flight refusals are expected along the way; the attempt cap is the bound
            if len(granted) >= 25:
                break
            rid = _reserve(ledger)
            if rid:
                granted.append(rid)
                _settle_ok(ledger, rid, tokens=10)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 25 == len(set(granted))
    assert Ledger(max_attempts=25).summary()["attempts"] == 25
