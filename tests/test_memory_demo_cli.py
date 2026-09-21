import argparse
import json

import pytest

from gibsey_lab import session_log
from gibsey_lab.memory import cli, contextual, demo, offers
from gibsey_lab.scoring import mock_dispatch
from test_memory_helpers import ScriptedDispatch, atlas_config, ev, make_field, make_rows

SCORES = {"LF2": {"contradiction": 1.0}, "PR5": {"development": 0.9}, "P1": {"bridge_relation": 0.67},
          "LF5": {"echo": 0.9}, "PR6": {"echo": 0.6}}


@pytest.fixture(autouse=True)
def stores(tmp_path, monkeypatch):
    monkeypatch.setattr(contextual, "ASSESSMENTS_PATH", tmp_path / "contextual" / "assessments.jsonl")
    monkeypatch.setattr(offers, "OFFER_SETS_PATH", tmp_path / "contextual" / "offer_sets.jsonl")
    monkeypatch.setattr(demo, "DEMO_DIR", tmp_path / "demos" / "pr2_memory")
    return tmp_path


def _run(field, dispatch, scores=SCORES):
    rows = make_rows(field, "PR2", scores)
    return demo.run_demo(dispatch=dispatch, mode="mock", requested_model="jev-test", field=field,
                         profiles_provider=lambda source, mode: rows, atlas_config_provider=atlas_config)


def test_demo_writes_files_and_holds_everything_but_history_constant(stores):
    field = make_field()
    dispatch = ScriptedDispatch()
    summary = _run(field, dispatch)
    out = stores / "demos" / "pr2_memory"
    assert sorted(p.name for p in out.iterdir()) == ["comparison.html", "condition_a.json", "condition_b.json",
                                                     "condition_c.json", "summary.json"]
    conditions = {k: json.loads((out / f"condition_{k}.json").read_text()) for k in "abc"}
    assert [conditions[k]["demo"]["declared_path"] for k in "abc"] == [["PR1", "PR3", "PR2"], ["LF3", "PR2"], ["PR2"]]
    orders = [[e["destination_id"] for e in conditions[k]["shortlist"]] for k in "abc"]
    assert orders[0] == orders[1] == orders[2] == summary["held_constant"]["shortlist_ids_in_order"] != []
    assert len({conditions[k]["page_sha256"] for k in "abc"}) == 1
    assert len({json.dumps(conditions[k]["versions"], sort_keys=True) for k in "abc"}) == 1
    assert len({conditions[k]["policy"] for k in "abc"}) == 1
    assert all(conditions[k]["memory_packet"]["source"] == "demonstration_fixture" for k in "abc")
    assert len({conditions[k]["memory_sha256"] for k in "abc"}) == 3

    assert summary["provider_input_differed_for_every_candidate"] is True
    for hashes in summary["request_sha256_by_candidate"].values():
        assert len(set(hashes.values())) == 3
    assert len(dispatch.requests) == 3 * len(orders[0])
    assert {q for r in dispatch.requests for q in (r.questions,)} == {contextual.QUESTIONS}
    assert len(summary["static_base_only"]) == len(orders[0])
    # fixtures never enter the reader's offer-set store or the session log
    assert not offers.OFFER_SETS_PATH.exists()
    assert all(r["memory_source"] == "demonstration_fixture" for r in contextual.read_records())


def test_demo_html_is_self_contained_escaped_and_shows_the_supplied_history(stores):
    field = make_field()
    _run(field, mock_dispatch)
    page = (stores / "demos" / "pr2_memory" / "comparison.html").read_text()
    assert "Demonstration fixtures — not the reader&#x27;s actions, not accepted bonds" in page
    assert "<b>distinct</b>" not in page and "&lt;b&gt;distinct&lt;/b&gt;" in page and "&amp; more." in page
    for forbidden in ("<script", "http://", "https://", "<link", "<img", "@import"):
        assert forbidden not in page
    assert "tokpr1" in page and "tokpr3" in page and "toklf3" in page and "(empty history)" in page
    for qid in contextual.QUESTION_IDS:
        assert qid in page
    assert "mock-lexical-overlap-v1" in page and "base-only ranking would offer" in page and "Request hashes" in page


def test_demo_does_not_require_a_winner_flip_or_any_offer(stores):
    field = make_field()
    same = _run(field, ScriptedDispatch())
    assert len({tuple(c["offers"]) for c in same["conditions"].values()}) == 1  # identical winners is a valid result
    empty = _run(field, ScriptedDispatch(), scores={})
    assert empty["held_constant"]["shortlist_ids_in_order"] == []
    assert {c["state"] for c in empty["conditions"].values()} == {"no_qualified"}
    assert "shortlist is empty" in (stores / "demos" / "pr2_memory" / "comparison.html").read_text()


def _parser():
    parser = argparse.ArgumentParser()
    cli.register_cli(parser.add_subparsers(dest="command", required=True))
    return parser


def test_cli_registers_commands_and_live_is_lead_wired(capsys):
    parser = _parser()
    args = parser.parse_args(["offers", "PR2", "--live"])
    assert args.func is cli.cmd_offers and args.func(args) == 2
    assert "lead-wired" in capsys.readouterr().err
    args = parser.parse_args(["pr2-demo", "--live"])
    assert args.func(args) == 2
    with pytest.raises(SystemExit):
        parser.parse_args(["pr2-demo"])  # --mock or --live is required
    with pytest.raises(SystemExit):
        parser.parse_args(["offers", "PR2", "--mock", "--live"])


def test_cli_memory_packet_is_read_only_and_short(tmp_path, monkeypatch, capsys):
    field = make_field()
    log = tmp_path / "session_log.jsonl"
    log.write_text("".join(json.dumps(e) + "\n" for e in [
        ev("page_viewed", "PR1"), ev("accept_and_follow", source="PR1", operator="DEVELOP", destination="PR4"),
        ev("page_viewed", "PR4", via="traversal")]))
    before = log.read_bytes()
    monkeypatch.setattr(session_log, "DEFAULT_LOG_PATH", log)
    monkeypatch.setattr(cli, "load_field", lambda field_id: field)
    args = _parser().parse_args(["memory-packet"])
    assert args.func(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["current"]["page_id"] == "PR4" and printed["current"]["operator"] == "DEVELOP"
    assert [e["page_id"] for e in printed["encounters"]] == ["PR1"] and "text" not in printed["encounters"][0]
    assert log.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == ["session_log.jsonl"]


def test_cli_offers_mock_uses_injected_atlas(monkeypatch, capsys, tmp_path):
    field = make_field()
    rows = make_rows(field, "PR2", SCORES)
    monkeypatch.setattr(cli, "load_field", lambda field_id: field)
    monkeypatch.setattr(session_log, "DEFAULT_LOG_PATH", tmp_path / "absent.jsonl")
    monkeypatch.setattr(offers, "_default_profiles_provider", lambda source, mode: rows)
    monkeypatch.setattr(offers, "_default_atlas_config_provider", atlas_config)
    args = _parser().parse_args(["offers", "PR2", "--mock"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "state=" in out and "mode=mock" in out and len(out.splitlines()) <= 4
