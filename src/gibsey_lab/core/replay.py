"""Provider-disabled replay checks (v0.3 plan §7).

1. State replay: fold every journaled event through the pinned reducer and compare the
   canonical state after each event with the `revision_after` the journal declared, and
   the final state with what `resume_session` reports.
2. Decision replay: for every `offer_set_created` event, recompute the offer set from the
   frozen atlas (the same options provider Core uses, no provider call) at that event's
   source version and compare bond ids and order with what was persisted. Drift means the
   atlas or the ranking policy changed since the offer was made; the stored offer still
   shows what was offered.

Neither check calls a model, writes to the journal, or creates reader activity.
"""
from __future__ import annotations

from pathlib import Path

from . import identity, journal, reducer
from .core import Core, bond_wording


def state_replay(session_id: str, core: Core) -> dict:
    events = journal.read_events(session_id, core.core_dir)
    trace = reducer.reduce_with_trace(events)
    mismatches = [
        {"seq": t["seq"], "declared": e.get("revision_after"), "reduced": t["state"]["r"]}
        for e, t in zip(events, trace) if e.get("revision_after") is not None and e["revision_after"] != t["state"]["r"]
    ]
    final = trace[-1]["state"] if trace else reducer.State().canonical()
    live = core.resume_session(session_id)["state"]
    return {"check": "state_replay", "session_id": session_id, "events": len(events), "per_event_mismatches": mismatches,
            "final_equal": final == live, "final_revision": final.get("r"), "encounters": len(final.get("H") or []),
            "ok": not mismatches and final == live}


def decision_replay(session_id: str, core: Core) -> dict:
    events = journal.read_events(session_id, core.core_dir)
    results = []
    for event in events:
        if event.get("event") != "offer_set_created":
            continue
        page = identity.page_of(event["source_version"])
        current_version = core._version(page)
        if current_version != event["source_version"]:
            results.append({"offer_set_id": event["offer_set_id"], "seq": event["seq"], "ok": False,
                            "reason": f"source version changed: offered at {event['source_version']}, now {current_version}"})
            continue
        recomputed = core._options(page, event["operator"], event["policy"])
        ids = []
        for option in recomputed.get("options") or []:
            dest = option["destination_id"]
            wording = bond_wording(core.field.manifest[dest].text)
            ids.append(identity.bond_version_id(source_version=event["source_version"],
                                                destination_version=core._version(dest), operator=event["operator"],
                                                wording=wording))
        stored = list(event.get("bond_version_ids") or [])
        results.append({"offer_set_id": event["offer_set_id"], "seq": event["seq"], "ok": ids == stored,
                        "stored": stored, "recomputed": ids,
                        "policy_version": {"stored": event.get("options_policy_version"),
                                           "now": recomputed.get("policy_version")}})
    return {"check": "decision_replay", "session_id": session_id, "offer_sets": len(results),
            "drift": [r for r in results if not r["ok"]], "ok": all(r["ok"] for r in results)}


def replay(session_id: str, core: Core) -> dict:
    s, d = state_replay(session_id, core), decision_replay(session_id, core)
    return {"session_id": session_id, "provider_calls": 0, "state_replay": s, "decision_replay": d, "ok": s["ok"] and d["ok"]}


def export_bundle(session_id: str, core: Core, out_dir: Path) -> Path:
    """Self-contained journey bundle: events, the exact prose of every version encountered
    (retained bytes), the atlas config, and the replay result."""
    import json
    from ..atlas import api as atlas_api

    events = journal.read_events(session_id, core.core_dir)
    state = reducer.reduce(events)
    versions = {}
    for h in state.H:
        page = core.field.manifest.get(h["page_id"])
        current = page is not None and identity.version_id(h["page_id"], page.sha256) == h["version_id"]
        versions[h["version_id"]] = {"page_id": h["page_id"], "text": page.text if current else None,
                                     "sha256": page.sha256 if current else None,
                                     "retained": current, "note": None if current else "version no longer current; bytes not retained"}
    bundle = {
        "schema": "journey-bundle/1", "session_id": session_id, "events": events, "final_state": state.canonical(),
        "versions": versions, "atlas_config": atlas_api.active_config("live"), "dspy_used": False,
        "replay": replay(session_id, core),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"journey_{session_id}.json"
    path.write_text(json.dumps(bundle, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
