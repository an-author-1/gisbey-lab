"""From the active page to at most three offered routes, every step recorded.

Pipeline (each step appears in the result):
  40 base profiles (atlas) -> eligibility (candidate policy; incomplete/stale/failed
  profiles are ineligible and counted) -> deterministic shortlist (<= 8, with reasons) ->
  memory packet -> history-conditioned assessment of THE SHORTLIST ONLY (one request per
  candidate, three separate questions) -> qualification -> ranking -> <= 3 offers.

`not_assessed_count` says how many eligible destinations received NO history-conditioned
assessment; nothing here claims all 40 were judged against the reader's history.

Qualification (PROVISIONAL application policy, on score_norm 0..1):
  works_after_history >= WORKS_FLOOR, grounded_reading_effect >= GROUNDED_FLOOR,
  repeats_recent_reading <= REPEATS_CEILING. A candidate failing any one is listed in
  `rejected` with the reason.

Version history: offers-v1 used WORKS_FLOOR = GROUNDED_FLOOR = 0.5. offers-v2 sets both to
2/3 (an expected score of 2.0 of 3: level 2 is the first level that asserts something
definite), for the same reason the shortlist relation floor moved in shortlist-v2: on the
complete live atlas a 0.5 floor did no work and the pilot scored an intended-weak pair
~0.62. Set once, on rubric meaning, before any live contextual data existed; still
provisional application policy. REPEATS_CEILING, MAX_OFFERS and the ranking rule are
unchanged from v1.

Ranking (documented, ordered, no hidden scalar). Each contextual answer is first read at
the rubric's own resolution -- its nearest level, 0..3 -- then candidates are ordered by:
  1. works_after_history level, higher first
  2. grounded_reading_effect level, higher first
  3. repeats_recent_reading level, lower first
  4. tie-break: best supporting BASE relation score_norm, higher first
  5. tie-break: field page order
The three answers are never summed or averaged. `rank_reasons` states the values used.

States: `no_candidates` (the policy leaves nothing eligible) / `atlas_incomplete`
(eligible pages exist but none has a complete base profile) / `no_qualified` (shortlist
empty, or assessed and none cleared the thresholds) / `error` (the atlas could not be
read, or every contextual request failed; partial failures are listed in `errors` and the
rest proceed) / `offers`.

Offers are never padded to three, never forced to include a contradiction, a cross-text
move, a revisit, or a non-neighbor, and revisits are not banned. `relation_labels` come
only from base dimensions that cleared their floor for that exact pair. Base data is
labeled `layer: "base_pair_profile"`; only a record from `contextual.assess` is labeled
`history_conditioned`. No randomness.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from ..corpus import REPO_ROOT
from ..fields import Field
from ..scoring import Dispatch
from . import contextual, shortlist as shortlist_mod
from .packet import MEMORY_POLICY_VERSION, build_memory_packet, memory_sha256

OFFER_POLICY_VERSION = "offers-v2"
OFFER_RESULT_SCHEMA = "offer-result/1"
OFFER_SETS_PATH = REPO_ROOT / "data" / "contextual" / "offer_sets.jsonl"

MAX_OFFERS = 3
# PROVISIONAL thresholds on score_norm (rubric levels 0..3 map to 0, .33, .67, 1).
WORKS_FLOOR = 2 / 3
GROUNDED_FLOOR = 2 / 3
REPEATS_CEILING = 0.67

BASE_LAYER = "base_pair_profile"
PROFILE_STATUSES = ("complete", "stale", "failed", "unassessed")

ProfilesProvider = Callable[[str, str], list[dict]]
AtlasConfigProvider = Callable[[str], dict]


def _default_profiles_provider(source_id: str, mode: str) -> list[dict]:
    from ..atlas import api  # lazy: the atlas package is never imported at module import time

    return api.profiles_for_source(source_id, mode)


def _default_atlas_config_provider(mode: str) -> dict:
    from ..atlas import api

    return api.active_config(mode)


def _pinned_model(atlas_config: dict) -> str | None:
    for key in ("pinned_returned_model", "returned_model", "pinned_model"):
        value = atlas_config.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _level(score: float) -> int:
    return int(score + 0.5)  # nearest rubric level; .5 rounds up, deterministically


def _answers_summary(record: dict) -> dict:
    out = {}
    for qid in contextual.QUESTION_IDS:
        a = (record.get("answers") or {}).get(qid) or {}
        out[qid] = {k: a.get(k) for k in ("score", "score_norm", "max_level", "confidence", "valid")}
    return out


def qualify(answers: dict) -> list[str]:
    """Reasons this candidate does NOT qualify; empty means qualified."""
    reasons = []
    works = answers["works_after_history"]["score_norm"]
    grounded = answers["grounded_reading_effect"]["score_norm"]
    repeats = answers["repeats_recent_reading"]["score_norm"]
    if not shortlist_mod.clears(works, WORKS_FLOOR):
        reasons.append(f"works_after_history {works:.2f} below floor {WORKS_FLOOR:.3f}")
    if not shortlist_mod.clears(grounded, GROUNDED_FLOOR):
        reasons.append(f"grounded_reading_effect {grounded:.2f} below floor {GROUNDED_FLOOR:.3f}")
    if repeats > REPEATS_CEILING:
        reasons.append(f"repeats_recent_reading {repeats:.2f} above ceiling {REPEATS_CEILING}")
    return reasons


def static_ranking(shortlist: dict | list[dict]) -> list[dict]:
    """What a base-only ordering would have offered: the shortlist's own order (best
    supporting base relation, then page order), first MAX_OFFERS marked `would_offer`.
    Shown beside the history-conditioned offers so the contribution of history is visible."""
    entries = shortlist["entries"] if isinstance(shortlist, dict) else list(shortlist)
    ranked = sorted(entries, key=lambda e: (-(e.get("best_score_norm") or 0.0), e.get("position", 0)))
    return [
        {"rank": i, "destination_id": e["destination_id"], "best_relation": e.get("best_relation"),
         "best_score_norm": e.get("best_score_norm"), "relation_labels": list(e.get("relation_labels") or []),
         "layer": BASE_LAYER, "would_offer": i <= MAX_OFFERS}
        for i, e in enumerate(ranked, start=1)
    ]


def _append(result: dict, path: Path | None) -> None:
    path = Path(path) if path is not None else OFFER_SETS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def build_offers(field: Field, page_id: str, events: Iterable[dict], *, policy: str, dispatch: Dispatch, mode: str,
                 requested_model: str, intention: str | None = None, memory_override: dict | None = None,
                 fixed_shortlist: dict | list[dict] | None = None, reuse_cache: bool = True,
                 profiles_provider: ProfilesProvider | None = None,
                 atlas_config_provider: AtlasConfigProvider | None = None, persist: bool = True) -> dict:
    if page_id not in field.manifest:
        raise ValueError(f"page {page_id!r} is not in field {field.id!r}")
    page = field.manifest[page_id]
    now = datetime.now(timezone.utc)

    if memory_override is not None:
        current = memory_override.get("current") or {}
        if current.get("page_id") != page_id or current.get("sha256") != page.sha256:
            raise ValueError("memory_override was built for a different current page or page version")
        packet = memory_override
    else:
        packet = build_memory_packet(field, page_id, events, candidate_policy=policy, intention=intention)

    result = {
        "schema": OFFER_RESULT_SCHEMA,
        "offer_set_id": f"offers_{now.strftime('%Y%m%dT%H%M%SZ')}_{page_id}_{uuid.uuid4().hex[:8]}",
        "at": now.isoformat(),
        "field": field.id,
        "page_id": page_id,
        "page_sha256": page.sha256,
        "policy": policy,
        "mode": mode,
        "state": None,
        "state_detail": None,
        "memory_source": packet.get("source"),
        "memory_packet": packet,
        "memory_sha256": memory_sha256(packet),
        "base_counts": {},
        "shortlist": [],
        "shortlist_excluded": [],
        "shortlist_counts": {},
        "shortlist_fixed": fixed_shortlist is not None,
        "static_base_only": [],
        "assessed_ids": [],
        "assessed": [],
        "not_assessed_count": 0,
        "offers": [],
        "rejected": [],
        "versions": {
            "offer_policy": OFFER_POLICY_VERSION,
            "shortlist_policy": shortlist_mod.SHORTLIST_POLICY_VERSION,
            "memory_policy": packet.get("policy_version", MEMORY_POLICY_VERSION),
            "contextual_rubric": contextual.CONTEXTUAL_RUBRIC_VERSION,
            "requested_model": requested_model,
            "atlas_config_id": None,
            "atlas_rubric_version": None,
            "pinned_returned_model": None,
            "returned_models": [],
        },
        "thresholds": {
            "works_floor": WORKS_FLOOR, "grounded_floor": GROUNDED_FLOOR, "repeats_ceiling": REPEATS_CEILING,
            "max_offers": MAX_OFFERS, "shortlist": shortlist_mod.thresholds(),
            "status": "provisional application policy",
        },
        "usage": {"requests_dispatched": 0, "cache_hits": 0, "attempts": 0, "input_tokens": 0, "output_tokens": 0,
                  "usage_unknown_requests": 0},
        "errors": [],
    }

    def finish(state: str, detail: str | None = None) -> dict:
        result["state"] = state
        result["state_detail"] = detail
        if persist:
            _append(result, None)
        return result

    # 1. base profiles + atlas configuration
    try:
        atlas_config = (atlas_config_provider or _default_atlas_config_provider)(mode) or {}
        profiles = list((profiles_provider or _default_profiles_provider)(page_id, mode))
    except Exception as e:  # noqa: BLE001 -- an unreadable atlas is a visible error, not an empty one
        result["errors"].append(f"could not read base profiles: {type(e).__name__}: {e}")
        return finish("error", "atlas_unreadable")
    pinned = _pinned_model(atlas_config)
    result["versions"].update(atlas_config_id=atlas_config.get("config_id"),
                              atlas_rubric_version=atlas_config.get("rubric_version"), pinned_returned_model=pinned)

    # 2. eligibility
    eligible = field.eligible_candidate_ids(page_id, policy)
    rows = {row["destination_id"]: row for row in profiles}
    usable = [
        pid for pid in eligible
        if rows.get(pid, {}).get("status") == "complete"
        and rows[pid].get("destination_sha256") in (None, field.manifest[pid].sha256)
    ]
    counts = {status: sum(1 for r in profiles if r.get("status") == status) for status in PROFILE_STATUSES}
    result["base_counts"] = {
        "profile_rows": len(profiles), **counts,
        "eligible": len(eligible),
        "ineligible_policy": len(field.candidate_ids_for(page_id)) - len(eligible),
        "eligible_complete": len(usable),
        "ineligible_incomplete": len(eligible) - len(usable),
    }
    result["not_assessed_count"] = len(eligible)
    if not eligible:
        return finish("no_candidates")
    if not usable:
        return finish("atlas_incomplete")

    # 3. shortlist (deterministic; or the caller's fixed one, re-validated against eligibility)
    usable_set = set(usable)
    if fixed_shortlist is None:
        built = shortlist_mod.build_shortlist([rows[pid] for pid in usable], usable, page_order=field.all_ids())
        entries, result["shortlist_excluded"] = built["entries"], built["excluded"]
        result["shortlist_counts"] = built["counts"]
    else:
        given = fixed_shortlist["entries"] if isinstance(fixed_shortlist, dict) else list(fixed_shortlist)
        entries = []
        for entry in given:
            if entry["destination_id"] in usable_set:
                entries.append(entry)
            else:
                result["rejected"].append({"destination_id": entry["destination_id"], "stage": "fixed_shortlist",
                                           "reasons": ["not eligible with a complete base profile here"]})
    entries = entries[: shortlist_mod.SHORTLIST_CAP]
    result["shortlist"] = entries
    result["static_base_only"] = static_ranking(entries)
    if not entries:
        return finish("no_qualified", "empty_shortlist")

    # 4. history-conditioned assessment of the shortlist only
    order = {pid: i for i, pid in enumerate(field.all_ids())}
    qualified = []
    returned_models: list[str] = []
    for entry in entries:
        pid = entry["destination_id"]
        record = contextual.assess(
            packet, current_page=page, candidate_page=field.manifest[pid], dispatch=dispatch, mode=mode,
            requested_model=requested_model, atlas_config_id=atlas_config.get("config_id"),
            pinned_returned_model=pinned, reuse_cache=reuse_cache,
        )
        usage = result["usage"]
        if record["from_cache"]:
            usage["cache_hits"] += 1
        else:
            usage["requests_dispatched"] += 1
            usage["attempts"] += record.get("attempts") or 0
            if record.get("usage"):
                usage["input_tokens"] += record["usage"].get("input_tokens") or 0
                usage["output_tokens"] += record["usage"].get("output_tokens") or 0
            elif record.get("mode") == "live":
                usage["usage_unknown_requests"] += 1
        if record.get("returned_model") and record["returned_model"] not in returned_models:
            returned_models.append(record["returned_model"])

        summary = {
            "destination_id": pid, "status": record["status"], "layer": contextual.LAYER,
            "contextual_assessment_id": record["assessment_id"], "from_cache": record["from_cache"],
            "cache_key": record["cache_key"], "request_sha256": record["request_sha256"], "mode": record["mode"],
            "returned_model": record.get("returned_model"), "answers": None, "qualified": False, "reasons": [],
        }
        if record["status"] != "ok":
            message = "; ".join(record.get("errors") or []) or record["status"]
            result["errors"].append({"destination_id": pid, "status": record["status"], "message": message,
                                     "contextual_assessment_id": record["assessment_id"]})
            summary["reasons"] = [f"contextual assessment {record['status']}"]
            result["assessed"].append(summary)
            continue

        result["assessed_ids"].append(pid)
        answers = _answers_summary(record)
        summary["answers"] = answers
        reasons = qualify(answers)
        summary["qualified"], summary["reasons"] = not reasons, reasons
        result["assessed"].append(summary)
        if reasons:
            result["rejected"].append({"destination_id": pid, "stage": "qualification", "reasons": reasons})
        else:
            qualified.append((entry, record, answers))

    result["versions"]["returned_models"] = returned_models
    result["not_assessed_count"] = len(eligible) - len(result["assessed_ids"])
    if not result["assessed_ids"]:
        return finish("error", "every_contextual_request_failed")
    if not qualified:
        return finish("no_qualified", "none_cleared_thresholds")

    # 5. ranking: ordered rule over the separate answers; base relation only breaks ties
    def sort_key(item):
        entry, _record, answers = item
        return (
            -_level(answers["works_after_history"]["score"]),
            -_level(answers["grounded_reading_effect"]["score"]),
            _level(answers["repeats_recent_reading"]["score"]),
            -(entry.get("best_score_norm") or 0.0),
            order.get(entry["destination_id"], len(order)),
        )

    qualified.sort(key=sort_key)
    seen: set[str] = set()
    for entry, record, answers in qualified:
        pid = entry["destination_id"]
        if pid in seen or len(result["offers"]) >= MAX_OFFERS:
            if pid not in seen:
                result["rejected"].append({"destination_id": pid, "stage": "ranking",
                                           "reasons": [f"qualified but ranked below the {MAX_OFFERS} offered"]})
            seen.add(pid)
            continue
        seen.add(pid)
        row = rows[pid]
        result["offers"].append({
            "rank": len(result["offers"]) + 1,
            "destination_id": pid,
            "destination_sha256": field.manifest[pid].sha256,
            "relation_labels": shortlist_mod.relation_labels(row),
            "is_authored_neighbor": bool(row.get("is_authored_neighbor")),
            "base": {"layer": BASE_LAYER, "assessment_id": row.get("assessment_id"),
                     "dimensions": shortlist_mod.base_summary(row)},
            "contextual": {"layer": contextual.LAYER, "from_cache": record["from_cache"], "answers": answers,
                           "request_sha256": record["request_sha256"], "mode": record["mode"],
                           "returned_model": record.get("returned_model")},
            "contextual_assessment_id": record["assessment_id"],
            "from_cache": record["from_cache"],
            "shortlist_reasons": entry.get("reasons", []),
            "rank_reasons": [
                f"works_after_history level {_level(answers['works_after_history']['score'])} (score {answers['works_after_history']['score']:.2f})",
                f"grounded_reading_effect level {_level(answers['grounded_reading_effect']['score'])} (score {answers['grounded_reading_effect']['score']:.2f})",
                f"repeats_recent_reading level {_level(answers['repeats_recent_reading']['score'])} (score {answers['repeats_recent_reading']['score']:.2f}; lower ranks first)",
                f"tie-break: best base relation {entry.get('best_relation')} {(entry.get('best_score_norm') or 0.0):.2f}, then field page order",
            ],
        })
    return finish("offers")
