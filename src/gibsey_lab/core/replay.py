"""Provider-disabled state and decision replay from retained journey inputs."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import identity, journal, reducer
from .core import Core, bond_wording


def _state_report(events: list[dict], expected: dict, session_id: str) -> dict:
    compatibility = []
    if not any(event.get("score_contract") is not None for event in events):
        expected = copy.deepcopy(expected)
        for encounter in expected.get("H") or []:
            if "cause" not in encounter and encounter.get("via") != "manual":
                encounter["cause"] = None
                compatibility.append("legacy_encounter_cause_defaults")
        for request in (expected.get("requests") or {}).values():
            if "kind" not in request and request.get("bond_version_id"):
                request["kind"] = "action"
                compatibility.append("legacy_action_request_kind_defaults")
    try:
        trace = reducer.reduce_with_trace(events)
        final = trace[-1]["state"] if trace else reducer.State().canonical()
    except (ValueError, KeyError, TypeError, reducer.ReduceError) as error:
        return {"check": "state_replay", "session_id": session_id, "events": len(events),
                "ok": False, "final_equal": False, "error": str(error)}
    mismatches = [
        {"seq": item["seq"], "declared": event.get("revision_after"), "reduced": item["state"]["r"]}
        for event, item in zip(events, trace)
        if event.get("revision_after") is not None and event["revision_after"] != item["state"]["r"]
    ]
    return {"check": "state_replay", "session_id": session_id, "events": len(events),
            "per_event_mismatches": mismatches, "final_equal": final == expected,
            "final_revision": final.get("r"), "encounters": len(final.get("H") or []),
            "compatibility": sorted(set(compatibility)),
            "ok": not mismatches and final == expected}


def state_replay(session_id: str, core: Core) -> dict:
    events = journal.read_events(session_id, core.core_dir)
    try:
        expected = core.resume_session(session_id)["state"]
    except (ValueError, KeyError, TypeError, reducer.ReduceError) as error:
        return {"check": "state_replay", "session_id": session_id, "events": len(events),
                "ok": False, "final_equal": False, "error": str(error)}
    return _state_report(events, expected, session_id)


def _frozen_decision(event: dict, state: reducer.State) -> dict:
    from . import resolver

    result = {"offer_set_id": event["offer_set_id"], "seq": event["seq"],
              "compatibility": "retained_score_inputs", "available": True}
    required = ("candidate_inputs", "resolver_inputs", "score_config_sha256", "decision_fingerprint",
                "bonds", "decisions", "blocked")
    missing = [name for name in required if name not in event]
    if missing:
        return {**result, "ok": False, "reason": "missing_frozen_inputs", "missing": missing}
    if event.get("resolver_version") != "score-resolver/1":
        return {**result, "ok": False, "reason": "unsupported_resolver_version"}
    if event["score_config_sha256"] != state.z.get("config_sha256"):
        return {**result, "ok": False, "reason": "score_config_mismatch"}
    if event.get("revision") != state.r or event.get("source_version") != state.v:
        return {**result, "ok": False, "reason": "offer_state_mismatch"}
    if any(event["resolver_inputs"].get(name) != event.get(name) for name in ("operator", "policy")):
        return {**result, "ok": False, "reason": "resolver_metadata_mismatch"}
    fingerprint = identity._digest({name: event[name] for name in (
        "candidate_inputs", "resolver_inputs", "score_config_sha256", "bonds", "decisions", "blocked")})
    if fingerprint != event["decision_fingerprint"]:
        return {**result, "ok": False, "reason": "decision_fingerprint_mismatch"}
    offer_id = "offers_" + identity._digest({
        "session_id": state.session_id, "revision": state.r, "source_version": state.v,
        "operator": event["operator"], "policy": event["policy"],
        "score_config_sha256": event["score_config_sha256"], "decision_fingerprint": fingerprint,
    })[:20]
    if offer_id != event["offer_set_id"]:
        return {**result, "ok": False, "reason": "offer_fingerprint_mismatch"}
    recomputed = resolver.resolve(state, event["candidate_inputs"], event["resolver_inputs"])
    differences = [name for name in ("bonds", "decisions", "blocked") if recomputed[name] != event[name]]
    ids = [bond["bond_version_id"] for bond in recomputed["bonds"]]
    if ids != event.get("bond_version_ids"):
        differences.append("bond_version_ids")
    return {**result, "ok": not differences, "differences": differences,
            "stored": event.get("bond_version_ids"), "recomputed": ids,
            "reasons_equal": recomputed["decisions"] == event["decisions"],
            "blocked_equal": recomputed["blocked"] == event["blocked"]}


def _legacy_decision(event: dict, core: Core | None) -> dict:
    result = {"offer_set_id": event["offer_set_id"], "seq": event["seq"]}
    if core is None:
        return {**result, "ok": False, "available": False,
                "compatibility": "legacy_recorded_offers", "reason": "legacy_bundle_missing_frozen_inputs"}
    page = identity.page_of(event["source_version"])
    current_version = core._version(page)
    if current_version != event["source_version"]:
        return {**result, "ok": False, "available": True,
                "reason": f"source version changed: offered at {event['source_version']}, now {current_version}"}
    recomputed = core._options(page, event["operator"], event["policy"])
    ids = []
    for option in recomputed.get("options") or []:
        destination = option["destination_id"]
        ids.append(identity.bond_version_id(
            source_version=event["source_version"], destination_version=core._version(destination),
            operator=event["operator"], wording=bond_wording(core.field.manifest[destination].text)))
    stored = list(event.get("bond_version_ids") or [])
    policy_equal = event.get("options_policy_version") == recomputed.get("policy_version")
    atlas_equal = event.get("atlas_config_id") == recomputed.get("atlas_config_id")
    return {**result, "ok": ids == stored and policy_equal and atlas_equal,
            "available": True, "compatibility": "legacy_supplied_atlas", "atlas_config_equal": atlas_equal,
            "stored": stored, "recomputed": ids,
            "policy_version": {"stored": event.get("options_policy_version"), "now": recomputed.get("policy_version")}}


def _decision_report(events: list[dict], session_id: str, core: Core | None = None) -> dict:
    results = []
    state = reducer.State()
    scored = False
    for event in events:
        if event.get("score_contract") is not None:
            scored = True
        try:
            if event.get("event") == "offer_set_created":
                if scored or event.get("resolver_version") is not None:
                    results.append(_frozen_decision(event, state))
                else:
                    results.append(_legacy_decision(event, core))
            state = reducer.apply(state, event)
        except (ValueError, KeyError, TypeError, reducer.ReduceError) as error:
            results.append({"seq": event.get("seq"), "ok": False, "reason": "replay_input_invalid", "error": str(error)})
            break
    return {"check": "decision_replay", "session_id": session_id,
            "offer_sets": sum(event.get("event") == "offer_set_created" for event in events),
            "results": results, "drift": [result for result in results if not result["ok"]],
            "available": all(result.get("available", True) for result in results),
            "ok": all(result["ok"] for result in results)}


def decision_replay(session_id: str, core: Core) -> dict:
    return _decision_report(journal.read_events(session_id, core.core_dir), session_id, core)


def replay(session_id: str, core: Core) -> dict:
    state = state_replay(session_id, core)
    decisions = decision_replay(session_id, core)
    return {"session_id": session_id, "provider_calls": 0, "state_replay": state,
            "decision_replay": decisions, "ok": state["ok"] and decisions["ok"]}


def _retained_versions(events: list[dict]) -> dict:
    versions = {}
    for event in events:
        versions.update(event.get("retained_content") or {})
    return versions


def _content_report(events: list[dict], versions: dict) -> dict:
    required = set()
    scored = any(event.get("score_contract") is not None for event in events)
    for event in events:
        for name in ("version_id", "from_version", "to_version", "source_version"):
            if event.get(name):
                required.add(event[name])
        for candidate in (event.get("candidate_inputs") or event.get("bonds") or []) if scored else []:
            for name in ("source_version", "destination_version"):
                if candidate.get(name):
                    required.add(candidate[name])
    errors = []
    for version in sorted(required):
        snapshot = versions.get(version)
        if not snapshot or not snapshot.get("retained") or not isinstance(snapshot.get("text"), str):
            errors.append({"version_id": version, "reason": "missing_content_snapshot"})
            continue
        actual_sha = hashlib.sha256(snapshot["text"].encode("utf-8")).hexdigest()
        if (actual_sha != snapshot.get("sha256") or snapshot.get("page_id") != identity.page_of(version)
                or identity.version_id(snapshot["page_id"], actual_sha) != version):
            errors.append({"version_id": version, "reason": "content_fingerprint_mismatch"})
    return {"check": "retained_content", "scope": "all_frozen_candidates" if scored else "legacy_encountered_versions",
            "versions_required": len(required), "errors": errors, "ok": not errors}


def _score_bundle_report(data: dict) -> dict:
    events = data["events"]
    snapshots = {event["score_config_sha256"]: event["score_snapshot"] for event in events
                 if event.get("score_snapshot") is not None and event.get("score_config_sha256") is not None}
    scored = any(event.get("score_contract") is not None for event in events)
    errors = []
    if scored:
        if data.get("schema") != "journey-bundle/2":
            errors.append("scored_bundle_requires_schema_2")
        if not snapshots or data.get("score_snapshots") != snapshots:
            errors.append("missing_or_changed_score_snapshots")
        manifest = data.get("version_manifest") or {}
        if manifest.get("reducer_version") != reducer.VERSION:
            errors.append("missing_or_unsupported_reducer_version")
        if manifest.get("score_contract") != "score/1":
            errors.append("missing_or_unsupported_score_contract")
        if manifest.get("score_config_sha256") != sorted(snapshots):
            errors.append("score_version_manifest_mismatch")
        resolvers = sorted({event["resolver_version"] for event in events if event.get("resolver_version")})
        if manifest.get("resolver_versions") != resolvers:
            errors.append("resolver_version_manifest_mismatch")
        try:
            if data.get("state_trace") != reducer.reduce_with_trace(events):
                errors.append("missing_or_changed_state_trace")
        except (ValueError, KeyError, TypeError, reducer.ReduceError):
            errors.append("state_trace_cannot_be_reconstructed")
    return {"check": "score_bundle", "compatibility": "score/1" if scored else "legacy-neutral",
            "errors": errors, "ok": not errors}


def replay_bundle(bundle: Path | str | dict, *, legacy_core: Core | None = None) -> dict:
    """Replay frozen score inputs; historical decisions may explicitly use a supplied local atlas."""
    data = json.loads(Path(bundle).read_text(encoding="utf-8")) if isinstance(bundle, (str, Path)) else bundle
    if data.get("schema") not in ("journey-bundle/1", "journey-bundle/2"):
        raise ValueError(f"unsupported journey bundle schema: {data.get('schema')!r}")
    events = data["events"]
    session_id = data["session_id"]
    state = _state_report(events, data["final_state"], session_id)
    decisions = _decision_report(events, session_id, legacy_core)
    content = _content_report(events, data.get("versions") or {})
    score = _score_bundle_report(data)
    result = {"session_id": session_id, "provider_calls": 0, "state_replay": state,
              "decision_replay": decisions, "retained_content": content, "score_bundle": score,
              "ok": state["ok"] and decisions["ok"] and content["ok"] and score["ok"]}
    if not decisions["available"]:
        result["recorded_historical_replay"] = data.get("replay")
        result["compatibility_note"] = "Legacy recorded offers remain inspectable; offline decision reconstruction needs frozen inputs absent from this bundle."
    elif any(item.get("compatibility") == "legacy_supplied_atlas" for item in decisions["results"]):
        result["compatibility_note"] = "Legacy decision reconstruction used the explicitly supplied local atlas; the historical bundle alone does not contain these candidate inputs."
    return result


def export_bundle(session_id: str, core: Core, out_dir: Path) -> Path:
    """Retain score, resolver inputs, content and per-event state without provider calls."""
    events = journal.read_events(session_id, core.core_dir)
    state = reducer.reduce(events)
    versions = _retained_versions(events)
    scored = any(event.get("score_contract") is not None for event in events)
    if not scored:
        for encounter in state.H:
            page = core.field.manifest.get(encounter["page_id"])
            current = page is not None and identity.version_id(encounter["page_id"], page.sha256) == encounter["version_id"]
            versions[encounter["version_id"]] = {
                "page_id": encounter["page_id"], "text": page.text if current else None,
                "sha256": page.sha256 if current else None, "retained": current,
                "note": None if current else "version no longer current; bytes not retained",
            }
    score_snapshots = {event["score_config_sha256"]: event["score_snapshot"] for event in events
                       if event.get("score_snapshot") is not None}
    bundle = {
        "schema": "journey-bundle/2" if scored else "journey-bundle/1", "session_id": session_id,
        "events": events, "final_state": state.canonical(), "versions": versions,
        "score_snapshots": score_snapshots, "dspy_used": False, "replay": replay(session_id, core),
        "state_trace": reducer.reduce_with_trace(events),
        "version_manifest": {
            "event_schema": journal.SCHEMA, "score_contract": "score/1" if scored else "legacy-neutral",
            "reducer_version": reducer.VERSION,
            "resolver_versions": sorted({event["resolver_version"] for event in events if event.get("resolver_version")}),
            "score_config_sha256": sorted(score_snapshots),
            "options_policy_versions": sorted({event["options_policy_version"] for event in events if event.get("options_policy_version")}),
            "atlas_config_ids": sorted({event["atlas_config_id"] for event in events if event.get("atlas_config_id")}),
            "provider_calls": 0,
        },
    }
    if not scored:
        from ..atlas import api as atlas_api
        bundle["atlas_config"] = atlas_api.active_config("live")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"journey_{session_id}.json"
    path.write_text(json.dumps(bundle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
