"""Deterministic bounded shortlist over one source's 40 base pair profiles.

The shortlist decides which destinations receive a history-conditioned assessment. It is
built per relation -- there is no single universal score -- and every entry says why it
is there. Pages that came close but were left out say why too.

Rule (SHORTLIST_POLICY_VERSION):
1. Only rows that are eligible under the candidate policy AND have a `complete` base
   profile are considered; the rest are counted (`ineligible_policy`,
   `ineligible_incomplete`), never guessed at.
2. Gates: `direct_q_fit` must reach DIRECT_Q_FIT_FLOOR and `missing_context` must not
   exceed MISSING_CONTEXT_CEILING.
3. For each of echo, development, contradiction, bridge_relation: the top
   PER_RELATION_TOP gated rows whose score_norm reaches RELATION_FLOOR support that
   relation. A row whose `redundancy` exceeds REDUNDANCY_CEILING may be supported ONLY by
   echo (an echo can legitimately also be redundant); for any other relation that support
   is refused, and the refusal is recorded as a reason.
4. Union, dedupe, order by best supporting score_norm (desc) then field page order, cut
   at SHORTLIST_CAP.

All thresholds below are PROVISIONAL application policy, not findings about the texts.

Version history: shortlist-v1 used RELATION_FLOOR = 0.5 (midway between rubric levels 1
and 2), chosen before any live atlas existed. With the live atlas complete (1,640/1,640),
48-75% of pairs cleared 0.5 on echo/development/bridge_relation, so the floor did no work,
and the pilot showed an intended-weak pair scoring ~0.62. shortlist-v2 sets the floor ONCE,
on rubric meaning: level 2 of 3 is the first level that asserts something definite, so
the floor is an expected score of 2.0, i.e. score_norm 2/3 (an exact 2.0 passes). It was
set before any live contextual data existed and is still provisional. The same floor
governs `relation_labels`. Nothing else changed from v1. No randomness anywhere. A weak atlas legitimately yields a
short or empty shortlist; nothing is promoted to fill it.
"""
from __future__ import annotations

SHORTLIST_POLICY_VERSION = "shortlist-v2"
SHORTLIST_SCHEMA = "shortlist/1"

RELATION_DIMENSIONS = ("echo", "development", "contradiction", "bridge_relation")
ALL_DIMENSIONS = ("direct_q_fit", "echo", "development", "contradiction", "bridge_relation", "redundancy",
                  "missing_context")

# PROVISIONAL thresholds on score_norm (0..1; rubric levels 0..3 map to 0, .33, .67, 1).
RELATION_FLOOR = 2 / 3          # expected score 2.0 of 3: the first level asserting something definite
FLOOR_EPSILON = 1e-9            # so an expected score of exactly 2.0 (2.0/3) clears 2/3
DIRECT_Q_FIT_FLOOR = 0.34       # above "weak"
MISSING_CONTEXT_CEILING = 0.67  # at most "moderate" missing context
REDUNDANCY_CEILING = 0.67       # above this only echo may support the row
PER_RELATION_TOP = 2
SHORTLIST_CAP = 8


def thresholds() -> dict:
    return {
        "relation_floor": RELATION_FLOOR,
        "direct_q_fit_floor": DIRECT_Q_FIT_FLOOR,
        "missing_context_ceiling": MISSING_CONTEXT_CEILING,
        "redundancy_ceiling": REDUNDANCY_CEILING,
        "per_relation_top": PER_RELATION_TOP,
        "cap": SHORTLIST_CAP,
        "status": "provisional application policy",
    }


def clears(norm: float | None, floor: float) -> bool:
    return norm is not None and norm >= floor - FLOOR_EPSILON


def dimension_norm(row: dict, dim: str) -> float | None:
    value = (row.get("dimensions") or {}).get(dim)
    if not isinstance(value, dict):
        return None
    norm = value.get("score_norm")
    if norm is None and value.get("score") is not None and value.get("max_level"):
        norm = value["score"] / value["max_level"]
    return float(norm) if isinstance(norm, (int, float)) and not isinstance(norm, bool) else None


def relation_labels(row: dict) -> list[str]:
    """Relations whose base score cleared RELATION_FLOOR for this pair -- the ONLY labels a
    card may carry. Weak evidence is never relabeled to populate a card."""
    labels = []
    for dim in RELATION_DIMENSIONS:
        norm = dimension_norm(row, dim)
        if clears(norm, RELATION_FLOOR):
            labels.append(dim)
    return labels


def base_summary(row: dict) -> dict:
    dims = row.get("dimensions") or {}
    return {
        dim: {"score": (dims.get(dim) or {}).get("score"), "score_norm": dimension_norm(row, dim),
              "confidence": (dims.get(dim) or {}).get("confidence")}
        for dim in ALL_DIMENSIONS
    }


def _order_index(page_order: list[str] | None, ids) -> dict[str, int]:
    order = list(page_order) if page_order is not None else sorted(ids)
    index = {pid: i for i, pid in enumerate(order)}
    for pid in sorted(ids):
        index.setdefault(pid, len(index))
    return index


def build_shortlist(profiles: list[dict], eligible_ids: list[str], *, page_order: list[str] | None = None,
                    per_relation_top: int = PER_RELATION_TOP, cap: int = SHORTLIST_CAP) -> dict:
    eligible = set(eligible_ids)
    rows = {row["destination_id"]: row for row in profiles}
    order = _order_index(page_order, rows)

    complete: list[dict] = []
    ineligible_incomplete: list[str] = []
    for pid in sorted(eligible & set(rows), key=order.__getitem__):
        row = rows[pid]
        if row.get("status") == "complete" and all(dimension_norm(row, d) is not None for d in ALL_DIMENSIONS):
            complete.append(row)
        else:
            ineligible_incomplete.append(pid)
    missing_rows = sorted(eligible - set(rows))
    ineligible_incomplete.extend(missing_rows)  # no profile row at all is also "not complete"

    excluded: dict[str, list[str]] = {}
    gated: list[dict] = []
    for row in complete:
        pid = row["destination_id"]
        cleared = relation_labels(row)
        problems = []
        fit, missing = dimension_norm(row, "direct_q_fit"), dimension_norm(row, "missing_context")
        if fit < DIRECT_Q_FIT_FLOOR:
            problems.append(f"direct_q_fit {fit:.2f} below floor {DIRECT_Q_FIT_FLOOR}")
        if missing > MISSING_CONTEXT_CEILING:
            problems.append(f"missing_context {missing:.2f} above ceiling {MISSING_CONTEXT_CEILING}")
        if problems:
            if cleared:  # a near miss: some relation cleared its floor but a gate stopped it
                excluded[pid] = [f"cleared {', '.join(cleared)} but " + p for p in problems]
            continue
        gated.append(row)

    support: dict[str, list[dict]] = {}
    notes: dict[str, list[str]] = {}
    below_all_floors = 0
    for row in gated:
        if not relation_labels(row):
            below_all_floors += 1

    for dim in RELATION_DIMENSIONS:
        ranked = sorted(
            (row for row in gated if clears(dimension_norm(row, dim), RELATION_FLOOR)),
            key=lambda row: (-dimension_norm(row, dim), order[row["destination_id"]]),
        )
        taken = 0
        for row in ranked:
            pid = row["destination_id"]
            norm = dimension_norm(row, dim)
            redundancy = dimension_norm(row, "redundancy")
            if redundancy > REDUNDANCY_CEILING and dim != "echo":
                excluded.setdefault(pid, []).append(
                    f"{dim} {norm:.2f} cleared floor {RELATION_FLOOR:.3f} but redundancy {redundancy:.2f} is above "
                    f"ceiling {REDUNDANCY_CEILING}; only echo may support a redundant page"
                )
                continue
            if taken >= per_relation_top:
                excluded.setdefault(pid, []).append(
                    f"{dim} {norm:.2f} cleared floor {RELATION_FLOOR:.3f} but was not in the top {per_relation_top} for {dim}"
                )
                continue
            taken += 1
            support.setdefault(pid, []).append(
                {"relation": dim, "score_norm": norm, "floor": RELATION_FLOOR, "rank_in_relation": taken}
            )
            if redundancy > REDUNDANCY_CEILING:
                notes.setdefault(pid, []).append(
                    f"redundancy {redundancy:.2f} is above ceiling {REDUNDANCY_CEILING}; kept because it entered via echo"
                )

    def best(pid: str) -> dict:
        return max(support[pid], key=lambda r: (r["score_norm"], -RELATION_DIMENSIONS.index(r["relation"])))

    ranked_ids = sorted(support, key=lambda pid: (-best(pid)["score_norm"], order[pid]))
    for pid in ranked_ids[cap:]:
        excluded.setdefault(pid, []).append(f"supported but cut by the shortlist cap of {cap}")
    ranked_ids = ranked_ids[:cap]

    entries = []
    for position, pid in enumerate(ranked_ids, start=1):
        row = rows[pid]
        entries.append({
            "position": position,
            "destination_id": pid,
            "destination_sha256": row.get("destination_sha256"),
            "base_assessment_id": row.get("assessment_id"),
            "is_authored_neighbor": bool(row.get("is_authored_neighbor")),
            "best_relation": best(pid)["relation"],
            "best_score_norm": best(pid)["score_norm"],
            "reasons": support[pid],
            "notes": notes.get(pid, []),
            "relation_labels": relation_labels(row),
            "base": base_summary(row),
        })

    shortlisted = set(ranked_ids)
    return {
        "schema": SHORTLIST_SCHEMA,
        "policy_version": SHORTLIST_POLICY_VERSION,
        "thresholds": {**thresholds(), "per_relation_top": per_relation_top, "cap": cap},
        "counts": {
            "profile_rows": len(rows),
            "eligible": len(eligible),
            "ineligible_policy": len(set(rows) - eligible),
            "ineligible_incomplete": len(ineligible_incomplete),
            "complete_eligible": len(complete),
            "failed_gates": len(complete) - len(gated),
            "below_all_relation_floors": below_all_floors,
            "shortlisted": len(entries),
        },
        "ineligible_incomplete_ids": ineligible_incomplete,
        "entries": entries,
        # Entries here partially cleared a floor but did not make the list. A page may
        # appear both as an entry (via one relation) and keep a refusal note for another.
        "excluded": [
            {"destination_id": pid, "shortlisted": pid in shortlisted, "excluded_reasons": reasons}
            for pid, reasons in sorted(excluded.items(), key=lambda item: order[item[0]])
        ],
    }
