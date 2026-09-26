"""Separate, provider-free material for the executable recurrence demonstration."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..corpus import Page
from ..fields import Field
from ..memory.operator_options import OPERATOR_DIMENSIONS
from .identity import OPERATORS, version_id

FIELD_ID = "recurrence-demo"
FIXTURE_ID = "recurrence-material/1"
ENTRY_PAGE = "RX1"

_TEXTS = {
    "RX1": (
        "The lamp waits in the window.\n\n"
        "Synthetic demonstration — The starting room.\n\n"
        "Take two paths into rooms you have not visited, then return here. "
        "The same lamp will be waiting; your recorded route will be different."
    ),
    "RX3": (
        "A small lamp shines beside the garden gate.\n\n"
        "Synthetic demonstration — The garden.\n\n"
        "The window is still visible behind you. In an ordinary journey you could "
        "return now. In the recurrence demonstration, visit one more new room first."
    ),
    "RX5": (
        "A lamp is reflected in the water.\n\n"
        "Synthetic demonstration — The pool.\n\n"
        "You can see the starting window in the reflection. After two outward "
        "arrivals, the return to that exact room becomes available."
    ),
    "RX7": (
        "A shaded lamp lights a narrow stair.\n\n"
        "Synthetic demonstration — The stair.\n\n"
        "This is another outward choice. A room already visited cannot count as "
        "a new room; the journey remembers each arrival in order."
    ),
}


def demo_field() -> Field:
    manifest = {
        page_id: Page(
            id=page_id, path=Path("synthetic") / FIXTURE_ID / f"{page_id}.md", text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), order=int(page_id[2:]),
        )
        for page_id, text in _TEXTS.items()
    }
    return Field(id=FIELD_ID, label="Synthetic recurrence demonstration", manifest=manifest)


def recurrence_score() -> dict:
    field = demo_field()
    return {
        "schema_version": 1,
        "score_id": "recurrence_fixture",
        "score_version": 1,
        "entry_version": version_id(ENTRY_PAGE, field.manifest[ENTRY_PAGE].sha256),
        "initial_movement": "outward",
        "global_actions": ["pause", "resume", "end_journey", "exit"],
        "relocation": {"permitted": False, "advances": False},
        "evidence": "supported_only",
        "movements": {
            "outward": {
                "allowed_functions": ["Q"], "allowed_operators": ["ECHO", "DEVELOP"],
                "guards": ["target_unvisited"], "advance_after": 2, "advance_on": ["Q"], "next": "return",
            },
            "return": {
                "allowed_functions": ["Q"], "allowed_operators": list(OPERATORS),
                "guards": ["target_is_entry_version", {"min_intervening_encounters": 2}],
                "advance_after": 1, "advance_on": ["Q"], "next": "complete",
            },
        },
        "terminal_movements": ["complete"],
        "empty_offer_behavior": "blocked_with_explanation",
    }


def fixture_options(field: Field, page_id: str, operator: str, policy: str) -> dict:
    if field.id != FIELD_ID or page_id not in field.manifest:
        raise ValueError("recurrence fixture options require their separate synthetic field")
    if operator not in OPERATORS:
        raise ValueError(f"unknown operator {operator!r}")
    eligible = field.eligible_candidate_ids(page_id, policy)
    destinations = eligible if operator in ("ECHO", "DEVELOP") else []
    options = [
        {
            "destination_id": destination, "destination_sha256": field.manifest[destination].sha256,
            "tier": "supported", "tier_label": "Synthetic fixture relationship",
            "operator_fit": {
                "dimension": OPERATOR_DIMENSIONS[operator], "score": 3.0, "score_norm": 1.0,
                "confidence": None, "nearest_level": 3,
            },
            "cautions": ["synthetic_fixture_not_a_model_assessment"],
            "assessment_id": f"fixture-recurrence-v1-{page_id}-{destination}-{operator}",
            "rank": rank,
            "rank_reasons": ["Declared synthetic relationship; ordered by fixture page identity."],
            "evidence_source": FIXTURE_ID,
            "evidence_kind": "synthetic_declared_relationship",
        }
        for rank, destination in enumerate(destinations, start=1)
    ]
    return {
        "schema": "operator-options/1", "policy_version": "recurrence-fixture-options-v1",
        "field": FIELD_ID, "page_id": page_id, "operator": operator, "policy": policy,
        "state": "options" if options else "no_candidates", "options": options,
        "counts": {
            "eligible": len(eligible), "usable": len(destinations), "supported": len(destinations),
            "supported_shown": len(destinations), "exploratory_shown": 0,
            "ineligible_policy": len(field.candidate_ids_for(page_id)) - len(eligible),
        },
        "unusable": [], "atlas_config_id": FIXTURE_ID, "atlas_rubric_version": "synthetic-declared-edges-v1",
        "pinned_returned_model": None, "evidence_source": "synthetic fixture; no provider or model assessment",
        "max_supported": len(destinations), "min_shown": 0,
    }
