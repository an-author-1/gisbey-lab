"""Deterministic gates before ordering over frozen candidate inputs."""
from __future__ import annotations

import copy

from . import scores

VERSION = "score-resolver/1"


def resolve(state, candidate_inputs: list[dict], resolver_inputs: dict) -> dict:
    decisions, eligible = [], []
    for candidate in candidate_inputs:
        checks = []
        for rule, allowed, code in (
            ("grounded", candidate.get("evidence_allowed", False), candidate.get("evidence_code", "evidence_unavailable")),
            ("source_matches", candidate.get("source_version") == state.v, "source_matches" if candidate.get("source_version") == state.v else "source_mismatch"),
            ("field_policy", candidate.get("policy_allowed", False), "policy_allowed" if candidate.get("policy_allowed") else "policy_ineligible"),
        ):
            checks.append(scores.decision(state, candidate, rule, bool(allowed), code,
                                          values={"policy": resolver_inputs["policy"]} if rule == "field_policy" else None))
        if state.z.get("config", {}).get("evidence") == "supported_only":
            supported = candidate.get("tier") == "supported"
            checks.append(scores.decision(state, candidate, "support_floor", supported,
                                          "supported" if supported else "below_support_floor",
                                          values={"tier": candidate.get("tier"), "operator_fit": candidate.get("operator_fit")}))
        checks.extend(scores.evaluate(state, candidate))
        decisions.extend(checks)
        if all(check["allowed"] for check in checks):
            eligible.append(candidate)
    ordered = sorted(eligible, key=lambda candidate: (candidate.get("rank") or 0, candidate["bond_version_id"]))
    maximum, minimum = resolver_inputs.get("max_supported"), resolver_inputs.get("min_shown")
    if maximum is not None:
        supported = [candidate for candidate in ordered if candidate.get("tier") == "supported"]
        chosen = supported[:maximum]
        if len(chosen) < (minimum or 0):
            chosen += [candidate for candidate in ordered if candidate.get("tier") != "supported"][:minimum - len(chosen)]
    else:
        chosen = ordered
    shown = {candidate["bond_version_id"] for candidate in chosen}
    for candidate in ordered:
        included = candidate["bond_version_id"] in shown
        decisions.append(scores.decision(state, candidate, "display_limit", included,
                                          "included" if included else "eligible_beyond_display_limit"))
    blocked = None if chosen else {
        "code": "blocked_with_explanation", "operator": resolver_inputs["operator"],
        "movement": state.z["movement"],
        "reason": "No available choice meets the current rules. Try another allowed relationship, or leave this journey.",
        "reason_codes": sorted({decision["code"] for decision in decisions if not decision["allowed"]}) or ["no_candidates"],
    }
    return {"bonds": copy.deepcopy(chosen), "decisions": decisions, "blocked": blocked}
