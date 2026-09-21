"""Ranked destinations for ONE operator from the existing base atlas -- no provider call.

Why this exists (contract section 8): the operator buttons used the single-winner Choice
path and the route hand thresholded one global shortlist, so a page could show no DEVELOP
option while the atlas held strong ones. Here every eligible destination with a usable
base profile is considered for the operator that was asked for.

Accessibility is separate from support. An option can always be previewed and followed;
its `tier` says how strongly the assessed relationship fits the operator:
- "supported": the operator's dimension has score_norm >= 2/3 (rubric level 2, the same
  floor as shortlist-v2).
- "exploratory": shown only to reach `min_shown`, labeled "Exploratory -- weak or
  uncertain fit". A weak fit is labeled, never hidden and never relabeled.

Guarantees:
- `operator_options` is pure and deterministic: no dispatch, no clock, no randomness, no
  hardcoded page ids. The same inputs give the same result and the same `option_set_id`
  (a hash of the result's content).
- Scores are never altered. `cautions` are descriptive flags only -- never exclusions,
  never score changes.
- A destination whose profile is missing, unassessed, stale, failed, or assessed against
  a different page version is listed in `unusable` with its status. It is never scored
  as zero and never ranked.
- Ranking v1: operator fit desc, then `direct_q_fit` desc, then field page order. Up to
  `max_supported` supported options; if fewer than `min_shown` are supported, the best
  remaining by the same ordering are appended as exploratory until `min_shown` are shown.
- `refine_with_history` assesses exactly the displayed options through
  `memory.contextual.assess` (so cache keys stay memory-, model- and version-strict and
  are shared with the route hand). It NEVER removes an option and never changes a tier or
  label. `ordering_basis` becomes "reading_history" only when every displayed option has
  a valid contextual answer; otherwise the base order stands and `refinement.state` says
  "partial" or "failed" with the per-option `contextual_error`. History ordering: tier
  first, then `works_after_history` score (0..3) desc, where a candidate within TIE_BAND
  of the leader of its group counts as tied and ties keep base order (measured rerun
  noise is <= 0.10), then base order.

All thresholds are provisional application policy, not findings about the texts.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Callable, Iterable

from ..fields import Field
from ..scoring import Dispatch
from . import contextual
from .packet import build_memory_packet, memory_sha256, summarize
from .shortlist import ALL_DIMENSIONS, RELATION_FLOOR, base_summary, clears, dimension_norm

OPERATOR_DIMENSIONS = {"ECHO": "echo", "DEVELOP": "development", "CONTRADICT": "contradiction",
                       "BRIDGE": "bridge_relation"}
OPTIONS_POLICY_VERSION = "operator-options-v1"
OPTIONS_SCHEMA = "operator-options/1"

SUPPORT_FLOOR = RELATION_FLOOR  # 2/3: rubric level 2, same floor as shortlist-v2
MAX_SUPPORTED = 5
MIN_SHOWN = 3
TIE_BAND = 0.15  # on the works_after_history score (0..3 scale)

TIER_SUPPORTED = "supported"
TIER_EXPLORATORY = "exploratory"
TIER_LABELS = {TIER_SUPPORTED: "Supported", TIER_EXPLORATORY: "Exploratory — weak or uncertain fit"}

LOW_CONFIDENCE = 0.5
HIGH_REDUNDANCY = 2 / 3
HIGH_MISSING_CONTEXT = 2 / 3
LOW_DIRECT_Q_FIT = 1 / 3
_EPS = 1e-9

BASE_ORDERING = "base_assessments"
HISTORY_ORDERING = "reading_history"

ProfilesProvider = Callable[[str, str], list[dict]]
AtlasConfigProvider = Callable[[str], dict]


def _default_profiles_provider(source_id: str, mode: str) -> list[dict]:
    from ..atlas import api  # lazy: never imported at module import time

    return api.profiles_for_source(source_id, mode)


def _default_atlas_config_provider(mode: str) -> dict:
    from ..atlas import api

    return api.active_config(mode)


def normalize_operator(operator: str) -> str:
    name = str(operator).strip().upper()
    if name not in OPERATOR_DIMENSIONS:
        raise ValueError(f"unknown operator {operator!r}; known operators: {sorted(OPERATOR_DIMENSIONS)}")
    return name


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _content_id(result: dict) -> str:
    body = {k: v for k, v in result.items() if k != "option_set_id"}
    return "opts_" + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:24]


def _usability(field: Field, page_id: str, destination_id: str, row: dict | None) -> str:
    """"usable", or the reason this profile may not be ranked."""
    if row is None:
        return "missing"
    status = row.get("status")
    if status != "complete":
        return status if status in ("stale", "failed", "unassessed") else f"not_complete:{status}"
    if row.get("destination_sha256") not in (None, field.manifest[destination_id].sha256):
        return "hash_mismatch"
    if row.get("source_sha256") not in (None, field.manifest[page_id].sha256):
        return "hash_mismatch"
    if any(dimension_norm(row, dim) is None for dim in ALL_DIMENSIONS):
        return "incomplete_dimensions"
    return "usable"


def _cautions(row: dict, dimension: str) -> list[str]:
    flags = []
    confidence = ((row.get("dimensions") or {}).get(dimension) or {}).get("confidence")
    if isinstance(confidence, (int, float)) and confidence < LOW_CONFIDENCE:
        flags.append("low_confidence")
    if clears(dimension_norm(row, "redundancy"), HIGH_REDUNDANCY):
        flags.append("high_redundancy")
    if clears(dimension_norm(row, "missing_context"), HIGH_MISSING_CONTEXT):
        flags.append("high_missing_context")
    if dimension_norm(row, "direct_q_fit") < LOW_DIRECT_Q_FIT - _EPS:
        flags.append("low_direct_q_fit")
    return flags


def operator_options(field: Field, page_id: str, operator: str, *, policy: str, mode: str = "live",
                     profiles_provider: ProfilesProvider | None = None,
                     atlas_config_provider: AtlasConfigProvider | None = None,
                     max_supported: int = MAX_SUPPORTED, min_shown: int = MIN_SHOWN) -> dict:
    operator = normalize_operator(operator)
    dimension = OPERATOR_DIMENSIONS[operator]
    if page_id not in field.manifest:
        raise ValueError(f"page {page_id!r} is not in field {field.id!r}")
    page = field.manifest[page_id]
    eligible = field.eligible_candidate_ids(page_id, policy)

    result = {
        "schema": OPTIONS_SCHEMA,
        "policy_version": OPTIONS_POLICY_VERSION,
        "option_set_id": None,
        "field": field.id,
        "page_id": page_id,
        "page_sha256": page.sha256,
        "operator": operator,
        "dimension": dimension,
        "policy": policy,
        "mode": mode,
        "atlas_config_id": None,
        "atlas_rubric_version": None,
        "pinned_returned_model": None,
        "ordering_basis": BASE_ORDERING,
        "support_floor": SUPPORT_FLOOR,
        "max_supported": max_supported,
        "min_shown": min_shown,
        "counts": {"eligible": len(eligible), "usable": 0, "unusable": 0, "supported": 0, "supported_shown": 0,
                   "exploratory_shown": 0, "ineligible_policy": len(field.candidate_ids_for(page_id)) - len(eligible)},
        "unusable": [],
        "state": None,
        "state_detail": None,
        "errors": [],
        "options": [],
    }

    def finish(state: str, detail: str | None = None) -> dict:
        result["state"], result["state_detail"] = state, detail
        result["option_set_id"] = _content_id(result)
        return result

    try:
        atlas_config = (atlas_config_provider or _default_atlas_config_provider)(mode) or {}
        profiles = list((profiles_provider or _default_profiles_provider)(page_id, mode))
    except Exception as e:  # noqa: BLE001 -- an unreadable atlas is a visible state, not an empty list
        result["errors"].append(f"could not read base profiles: {type(e).__name__}: {e}")
        return finish("atlas_unavailable", "atlas_unreadable")
    result["atlas_config_id"] = atlas_config.get("config_id")
    result["atlas_rubric_version"] = atlas_config.get("rubric_version")
    pinned = atlas_config.get("pinned_returned_model")
    result["pinned_returned_model"] = pinned if isinstance(pinned, str) and pinned else None

    if not eligible:
        return finish("no_candidates")

    rows = {row["destination_id"]: row for row in profiles}
    usable: list[dict] = []
    for pid in eligible:  # field page order
        verdict = _usability(field, page_id, pid, rows.get(pid))
        if verdict == "usable":
            usable.append(rows[pid])
        else:
            result["unusable"].append({"destination_id": pid, "status": verdict})
    result["counts"]["usable"] = len(usable)
    result["counts"]["unusable"] = len(result["unusable"])

    order = {pid: i for i, pid in enumerate(field.all_ids())}
    ranked = sorted(usable, key=lambda row: (-dimension_norm(row, dimension), -dimension_norm(row, "direct_q_fit"),
                                             order[row["destination_id"]]))
    supported = [row for row in ranked if clears(dimension_norm(row, dimension), SUPPORT_FLOOR)]
    shown = [(row, TIER_SUPPORTED) for row in supported[:max_supported]]
    if len(supported) < min_shown:
        remaining = [row for row in ranked if not clears(dimension_norm(row, dimension), SUPPORT_FLOOR)]
        shown += [(row, TIER_EXPLORATORY) for row in remaining[: min_shown - len(shown)]]
    result["counts"]["supported"] = len(supported)
    result["counts"]["supported_shown"] = sum(1 for _, tier in shown if tier == TIER_SUPPORTED)
    result["counts"]["exploratory_shown"] = sum(1 for _, tier in shown if tier == TIER_EXPLORATORY)

    for rank, (row, tier) in enumerate(shown, start=1):
        pid = row["destination_id"]
        fit = (row.get("dimensions") or {}).get(dimension) or {}
        norm = dimension_norm(row, dimension)
        score = fit.get("score")
        relation = "at or above" if tier == TIER_SUPPORTED else "below"
        result["options"].append({
            "rank": rank,
            "destination_id": pid,
            "destination_sha256": field.manifest[pid].sha256,
            "tier": tier,
            "tier_label": TIER_LABELS[tier],
            "operator_fit": {"dimension": dimension, "score": score, "score_norm": norm,
                             "confidence": fit.get("confidence"),
                             "nearest_level": int(score + 0.5) if isinstance(score, (int, float)) else None},
            "cautions": _cautions(row, dimension),
            "base": base_summary(row),
            "assessment_id": row.get("assessment_id"),
            "is_authored_neighbor": bool(row.get("is_authored_neighbor")),
            "rank_reasons": [
                f"{dimension} score_norm {norm:.2f} is {relation} the support floor {SUPPORT_FLOOR:.3f}: {tier}",
                f"ordered by {dimension} {norm:.2f}, then direct_q_fit {dimension_norm(row, 'direct_q_fit'):.2f}, "
                "then field page order",
            ] + ([f"shown to reach {min_shown} options; only {len(supported)} supported"]
                 if tier == TIER_EXPLORATORY else []),
        })

    if len(eligible) < min_shown:
        return finish("fewer_than_three_eligible")
    if not usable:
        return finish("atlas_unavailable", "no_usable_profiles")
    if len(result["options"]) < min_shown:
        return finish("options", "fewer_usable_profiles_than_min_shown")
    return finish("options")


# --------------------------------------------------------------------------- refinement


def _history_order(options: list[dict]) -> list[dict]:
    """Tier first; within a tier, works_after_history desc in tie groups anchored on each
    group's leader (a candidate within TIE_BAND of the leader is tied); ties keep base order."""
    ordered: list[dict] = []
    for tier in (TIER_SUPPORTED, TIER_EXPLORATORY):
        members = [o for o in options if o["tier"] == tier]
        by_score = sorted(members, key=lambda o: (-o["contextual"]["answers"]["works_after_history"]["score"], o["base_rank"]))
        group: list[dict] = []
        leader = None
        for option in by_score:
            score = option["contextual"]["answers"]["works_after_history"]["score"]
            if leader is not None and leader - score <= TIE_BAND + _EPS:
                group.append(option)
                continue
            ordered += sorted(group, key=lambda o: o["base_rank"])
            group, leader = [option], score
        ordered += sorted(group, key=lambda o: o["base_rank"])
    return ordered


def refine_with_history(option_set: dict, field: Field, events: Iterable[dict], *, dispatch: Dispatch, mode: str,
                        requested_model: str, intention: str | None = None, reuse_cache: bool = True) -> dict:
    refined = copy.deepcopy(option_set)
    options = refined.get("options") or []
    for option in options:
        option.setdefault("base_rank", option["rank"])
        option.pop("contextual", None)
        option.pop("contextual_error", None)
    refinement = {"state": "failed", "errors": [], "memory_sha256": None, "assessed_ids": [], "mode": mode,
                  "requested_model": requested_model, "tie_band": TIE_BAND, "tie_band_scale": "score (0..3)",
                  "requests_dispatched": 0, "cache_hits": 0, "memory_summary": None}
    refined["refinement"] = refinement
    refined["ordering_basis"] = BASE_ORDERING

    page_id = refined["page_id"]
    page = field.manifest.get(page_id)
    if page is None or page.sha256 != refined.get("page_sha256"):
        refinement["errors"].append("the current page has changed since this option set was built; not refined")
        return refined
    if not options:
        refinement["errors"].append("the option set has no displayed options to refine")
        return refined

    packet = build_memory_packet(field, page_id, events, candidate_policy=refined["policy"], intention=intention)
    refinement["memory_sha256"] = memory_sha256(packet)
    refinement["memory_summary"] = summarize(packet)

    for option in options:
        pid = option["destination_id"]
        candidate = field.manifest.get(pid)
        if candidate is None or candidate.sha256 != option.get("destination_sha256"):
            option["contextual_error"] = "this page has changed since its base assessment; not assessed"
            refinement["errors"].append({"destination_id": pid, "status": "hash_mismatch",
                                         "message": option["contextual_error"]})
            continue
        record = contextual.assess(
            packet, current_page=page, candidate_page=candidate, dispatch=dispatch, mode=mode,
            requested_model=requested_model, atlas_config_id=refined.get("atlas_config_id"),
            pinned_returned_model=refined.get("pinned_returned_model"), reuse_cache=reuse_cache,
        )
        refinement["cache_hits" if record["from_cache"] else "requests_dispatched"] += 1
        answers = record.get("answers") or {}
        valid = record["status"] == "ok" and all(
            isinstance((answers.get(qid) or {}).get("score"), (int, float)) for qid in contextual.QUESTION_IDS)
        if not valid:
            message = "; ".join(record.get("errors") or []) or f"contextual assessment {record['status']}"
            option["contextual_error"] = message
            refinement["errors"].append({"destination_id": pid, "status": record["status"], "message": message,
                                         "contextual_assessment_id": record["assessment_id"]})
            continue
        option["contextual"] = {
            "layer": contextual.LAYER, "from_cache": record["from_cache"],
            "contextual_assessment_id": record["assessment_id"], "request_sha256": record["request_sha256"],
            "mode": record["mode"], "returned_model": record.get("returned_model"),
            "answers": {qid: {k: answers[qid].get(k) for k in ("score", "score_norm", "max_level", "confidence")}
                        for qid in contextual.QUESTION_IDS},
        }
        refinement["assessed_ids"].append(pid)

    if len(refinement["assessed_ids"]) == len(options):
        refinement["state"] = "ok"
        refined["ordering_basis"] = HISTORY_ORDERING
        refined["options"] = _history_order(options)
        for rank, option in enumerate(refined["options"], start=1):
            option["rank"] = rank
            works = option["contextual"]["answers"]["works_after_history"]["score"]
            option["history_rank_reasons"] = [
                f"tier {option['tier']} first; works_after_history {works:.2f}; candidates within {TIE_BAND} "
                f"are tied and keep base order (base rank {option['base_rank']})"
            ]
    elif refinement["assessed_ids"]:
        refinement["state"] = "partial"
    return refined
