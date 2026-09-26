"""Bounded neutral ordering parity and ordered-history evidence without providers."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from gibsey_lab.atlas import api as atlas_api
from gibsey_lab.atlas import store as atlas_store
from gibsey_lab.core import identity, reducer, resolver, scores
from gibsey_lab.core.core import Core
from gibsey_lab.core.fixtures import ENTRY_PAGE, demo_field, fixture_options
from gibsey_lab.core.replay import decision_replay, state_replay
from gibsey_lab.fields import KNOWN_POLICIES, load_field

ROOT = Path(__file__).resolve().parents[2]


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parity_report(core_dir: Path) -> dict:
    field = load_field("full-41")
    config = atlas_api.active_config("live")
    records, record_count = atlas_api._records_by_pair("live")
    profiles = {
        source: [atlas_api._profile_row(field, config, source, destination,
                                       records.get((source, destination), []))
                 for destination in field.candidate_ids_for(source)]
        for source in field.all_ids()
    }
    core = Core(core_dir=core_dir, field=field)
    failures, comparisons = [], []
    with patch("gibsey_lab.memory.operator_options._default_profiles_provider",
               side_effect=lambda source, mode: copy.deepcopy(profiles[source])), patch(
                   "gibsey_lab.memory.operator_options._default_atlas_config_provider",
                   return_value=config):
        for source in field.all_ids():
            source_version = core._version(source)
            state = reducer.State(v=source_version, page=source, field_id=field.id,
                                  z=scores.initial(scores.neutral_score(), source_version))
            for operator in identity.OPERATORS:
                for policy in KNOWN_POLICIES:
                    legacy = core._options(source, operator, policy)
                    candidates, inputs, candidate_options = core._frozen_candidates(state, operator, policy)
                    resolved = resolver.resolve(state, candidates, inputs)
                    expected = [option["destination_id"] for option in legacy["options"]]
                    actual = [bond["destination_page"] for bond in resolved["bonds"]]
                    comparison = {"source_version": source_version, "operator": operator, "policy": policy,
                                  "expected": expected, "actual": actual, "equal": expected == actual}
                    comparisons.append(comparison)
                    if not comparison["equal"]:
                        failures.append({**comparison, "legacy_options": legacy,
                                         "candidate_options": candidate_options, "candidate_inputs": candidates,
                                         "resolver_inputs": inputs, "resolution": resolved})
    return {
        "kind": "neutral_ordering_parity_diagnostic_not_a_simulation", "provider_calls": 0,
        "ok": not failures and len(comparisons) == 328, "comparisons": len(comparisons),
        "sources": len(field.manifest), "operators": list(identity.OPERATORS), "policies": list(KNOWN_POLICIES),
        "failures": failures, "results": comparisons,
        "snapshot": {"atlas_config": config, "records_in_store": record_count,
                     "assessment_file_sha256": hashlib.sha256(Path(atlas_store.ASSESSMENTS_PATH).read_bytes()).hexdigest(),
                     "profile_snapshot_sha256": identity._digest(profiles),
                     "content_versions": {source: core._version(source) for source in field.all_ids()},
                     "resolver_version": resolver.VERSION, "score_contract": scores.CONTRACT,
                     "neutral_config": scores.neutral_score()},
        "code_references": ["src/gibsey_lab/core/core.py:Core._frozen_candidates",
                            "src/gibsey_lab/core/resolver.py:resolve",
                            "src/gibsey_lab/memory/operator_options.py:operator_options"],
    }


def history_report(core_dir: Path) -> dict:
    core = Core(core_dir=core_dir, field=demo_field(), options_provider=fixture_options)
    config = scores.neutral_score()
    config["score_id"] = "spacing_history_fixture"
    config["movements"]["open"]["guards"] = [{"min_intervening_encounters": 2}]
    histories = []
    for session, route in (("older", ["RX7", "RX3", "RX5"]), ("newer", ["RX3", "RX7", "RX5"])):
        core.start_session(ENTRY_PAGE, session_id=session, score_config=config)
        for index, destination in enumerate(route):
            core.relocate(session, page_id=destination, expected_revision=core.state(session).r,
                          request_id=f"arrival_{index}", cause="page_list")
        offer = core.resolve_options(session, "ECHO")
        state = core.state(session)
        deciding_guard = next(decision for decision in offer["decisions"]
                              if decision["destination_page"] == "RX7"
                              and decision["rule_id"].endswith("/min_intervening_encounters"))
        histories.append({"label": session, "ordered_encounters": state.H, "visit_counts": state.c,
                          "source_version": state.v, "score": state.z,
                          "offered_destinations": [bond["destination_page"] for bond in offer["bonds"]],
                          "deciding_guard": deciding_guard, "candidate_inputs": offer["candidate_inputs"],
                          "resolver_inputs": offer["resolver_inputs"],
                          "state_replay": state_replay(session, core),
                          "decision_replay": decision_replay(session, core)})
    older, newer = histories
    checks = {"same_source_version": older["source_version"] == newer["source_version"],
              "same_visit_counts": older["visit_counts"] == newer["visit_counts"],
              "same_frozen_relationships": older["candidate_inputs"] == newer["candidate_inputs"],
              "same_resolver_inputs": older["resolver_inputs"] == newer["resolver_inputs"],
              "distinct_ordered_histories": older["ordered_encounters"] != newer["ordered_encounters"],
              "older_allowed_newer_denied": older["deciding_guard"]["allowed"] and not newer["deciding_guard"]["allowed"],
              "candidate_arrival_indices": all(history["deciding_guard"]["values"]["candidate_arrival_index"] == 4 for history in histories),
              "intervening_boundary": [history["deciding_guard"]["values"]["intervening_encounters"] for history in histories] == [2, 1],
              "offline_replay": all(history["state_replay"]["ok"] and history["decision_replay"]["ok"] for history in histories)}
    return {"kind": "synthetic_ordered_history_comparison", "provider_calls": 0, "ok": all(checks.values()),
            "checks": checks, "histories": histories,
            "explanation": "RX7 was last encountered at index 1 versus 2. The same candidate arrival at index 4 has index distance 3 versus 2 and intervening count 2 versus 1. Only the older visit meets the minimum of two.",
            "code_references": ["src/gibsey_lab/core/scores.py:evaluate",
                                "tests/test_core_scores.py:test_ordered_histories_with_equal_counts_change_return_eligibility"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/verification/core_v03_session3_neutral_2026-09-25")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="gibsey-score-parity-") as directory:
        root = Path(directory)
        parity = parity_report(root / "neutral")
        history = history_report(root / "histories")
    save(args.output / "neutral_parity.json", parity)
    save(args.output / "history_dependence.json", history)
    print(json.dumps({"neutral_comparisons": parity["comparisons"], "neutral_failures": len(parity["failures"]),
                      "ordered_history_ok": history["ok"], "provider_calls": 0, "output": str(args.output)}))
    return 0 if parity["ok"] and history["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
