"""Reproduce provider-disabled replay evidence in temporary stores only."""
from __future__ import annotations

import hashlib
import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from gibsey_lab.core import fixtures, journal, replay, scores
from gibsey_lab.core.core import Core


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[2]


def unavailable(*args, **kwargs):
    raise AssertionError("providers, live candidate lookups and network are disabled")


def follow(core, session_id, destination, request_id):
    offer = core.resolve_options(session_id, "ECHO")
    selected = next(bond for bond in offer["bonds"] if bond["destination_page"] == destination)
    return core.execute_action(session_id, offer_set_id=offer["offer_set_id"],
                               bond_version_id=selected["bond_version_id"],
                               expected_revision=core.state(session_id).r, request_id=request_id)


def main():
    report = {"scope": "API and replay evidence; no browser observations", "network_disabled": True,
              "provider_calls": 0, "legacy_bundles": {}, "historical_journals": {}, "new_bundles": {}}
    historical = sorted((ROOT / "data/core/sessions").glob("*/events.jsonl"))
    for directory in ("core_v03_demo_2026-09-25", "core_v03_session2_demo_2026-09-25"):
        historical += sorted((ROOT / "data/verification" / directory).glob("journey_*.json"))
    before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in historical}
    with patch.object(socket.socket, "connect", unavailable), tempfile.TemporaryDirectory(prefix="gibsey-score-replay-") as temporary:
        for path in historical:
            if path.suffix == ".json":
                result = replay.replay_bundle(path, legacy_core=Core())
                report["legacy_bundles"][str(path.relative_to(ROOT))] = result
            else:
                result = replay.replay(path.parent.name, Core())
                report["historical_journals"][path.parent.name] = result
            assert result["ok"], result

        core = Core(core_dir=Path(temporary) / "core", field=fixtures.demo_field(),
                    options_provider=fixtures.fixture_options)
        session_id = "session3_recurrence_replay"
        core.start_session(fixtures.ENTRY_PAGE, session_id=session_id, score_config=fixtures.recurrence_score())
        blocked = core.resolve_options(session_id, "CONTRADICT")
        assert blocked["blocked"] and core.state(session_id).z["counter"] == 0
        core.pause(session_id)
        core.unpause(session_id)
        follow(core, session_id, "RX3", "outward-one")
        follow(core, session_id, "RX5", "outward-two")
        return_offer = core.resolve_options(session_id, "ECHO")
        report["return_guard"] = next(decision for decision in return_offer["decisions"]
                                      if decision["destination_page"] == "RX1" and decision["code"] == "return_spacing_satisfied")
        follow(core, session_id, "RX1", "return-home")
        assert core.state(session_id).z["status"] == "complete"
        assert core.state(session_id).z["counters"] == {"outward": 2, "return": 1}

        neutral = "session3_neutral_replay"
        core.start_session(fixtures.ENTRY_PAGE, session_id=neutral, score_config=scores.neutral_score())
        follow(core, neutral, "RX3", "neutral-outward")
        offer = core.resolve_options(neutral, "ECHO")
        assert any(bond["destination_page"] == "RX1" for bond in offer["bonds"])
        core.relocate(neutral, page_id="RX1", expected_revision=core.state(neutral).r,
                      request_id="neutral-relocation", cause="page_list")
        assert core.state(neutral).H[-1]["bond_version_id"] is None

        for outcome in ("end_journey", "exit"):
            lifecycle_session = f"session3_{outcome}_replay"
            core.start_session(fixtures.ENTRY_PAGE, session_id=lifecycle_session, score_config=fixtures.recurrence_score())
            core.lifecycle(lifecycle_session, action=outcome, expected_revision=core.state(lifecycle_session).r,
                           request_id=f"{outcome}-request")

        restarted = Core(core_dir=core.core_dir, field=core.field, options_provider=unavailable,
                         candidate_provider=unavailable)
        for name in (session_id, neutral, "session3_end_journey_replay", "session3_exit_replay"):
            assert restarted.state(name).canonical() == core.state(name).canonical()
            path = replay.export_bundle(name, restarted, OUTPUT)
            result = replay.replay_bundle(path)
            assert result["ok"], result
            report["new_bundles"][path.name] = result
            destination = journal.journal_path(name, OUTPUT / "core")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(journal.journal_path(name, core.core_dir).read_bytes())
    after = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in historical}
    assert before == after
    report["historical_files_unchanged"] = before == after
    report["historical_sha256"] = before
    report["ok"] = True
    (OUTPUT / "replay_result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": True, "legacy_bundles": len(report["legacy_bundles"]),
                      "historical_journals": len(report["historical_journals"]),
                      "new_bundles": len(report["new_bundles"]), "provider_calls": 0}))


if __name__ == "__main__":
    main()
