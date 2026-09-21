"""Shared fixtures and fakes for the atlas tests. Everything runs against tmp_path with
the path constants monkeypatched; nothing here can reach data/, runs/, or a provider."""
from __future__ import annotations

import hashlib
import threading
from dataclasses import replace

import pytest

from gibsey_lab import recorder, scoring
from gibsey_lab.atlas import api, ledger, store
from gibsey_lab.corpus import Page
from gibsey_lab.fields import EXPECTED_FULL_41_IDS, FULL_41, Field, _sort_key

LIVE_MODEL = "jev-9.9.9-test"


def make_page(page_id: str, text: str, tmp_path) -> Page:
    order = _sort_key(page_id)[1]
    return Page(id=page_id, path=tmp_path / f"{page_id}.md", text=text,
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), order=order)


class Env:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.manifest = {
            pid: make_page(pid, f"Synthetic passage {pid}. The lamp in room {i} flickers while someone counts to {i * 7}.", tmp_path)
            for i, pid in enumerate(EXPECTED_FULL_41_IDS, start=1)
        }

    def field(self) -> Field:
        return Field(id=FULL_41, label="synthetic 41", manifest=dict(self.manifest))

    def edit_page(self, page_id: str, text: str) -> None:
        self.manifest[page_id] = make_page(page_id, text, self.tmp_path)


@pytest.fixture
def atlas_env(tmp_path, monkeypatch) -> Env:
    env = Env(tmp_path)
    monkeypatch.setattr(store, "ASSESSMENTS_PATH", tmp_path / "atlas" / "assessments.jsonl")
    monkeypatch.setattr(api, "CONFIG_PATH", tmp_path / "atlas" / "active_config.json")
    monkeypatch.setattr(ledger, "LEDGER_PATH", tmp_path / "atlas" / "ledger.jsonl")
    monkeypatch.setattr(recorder, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(api, "current_field", env.field)
    return env


class CountingDispatch:
    """Wraps a dispatch and counts the requests that reach it (thread-safe)."""

    def __init__(self, inner):
        self.inner = inner
        self.requests = []
        self._lock = threading.Lock()

    def __call__(self, request):
        with self._lock:
            self.requests.append(request)
        return self.inner(request)

    @property
    def count(self) -> int:
        return len(self.requests)


def fake_live(returned_model: str = LIVE_MODEL, usage: dict | None = None):
    """A stand-in for the live gateway: well-formed answers stamped mode="live". It is a
    fake -- no network -- used to exercise live-view bookkeeping."""

    def dispatch(request):
        return replace(scoring.mock_dispatch(request), mode="live", returned_model=returned_model,
                       usage=usage or {"input_tokens": 1200, "output_tokens": 90}, attempts=1, elapsed_seconds=0.4)

    return dispatch


def failing_live(message: str = "ConnectionError: provider unreachable"):
    def dispatch(request):
        return scoring.ScoreOutcome("error", "live", request.requested_model, None, {}, None, 0.1, 3,
                                    [message] * 3, request.request_sha256())

    return dispatch


def invalid_live(returned_model: str = LIVE_MODEL, broken_dimension: str = "echo"):
    """A provider response whose answer for one dimension is malformed."""

    def dispatch(request):
        good = fake_live(returned_model)(request)
        answers = dict(good.answers)
        question = next(q for q in request.questions if q.qid == broken_dimension)
        answers[broken_dimension] = scoring.validate_answer(
            question, {"type": "score", "score": 9, "probabilities": {"0": 0.5, "1": 0.5}}
        )
        return replace(good, status="invalid", answers=answers)

    return dispatch
