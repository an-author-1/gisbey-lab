"""Context assembly for the reader app: builds a ContextPacket for (field, source,
operator, policy, criteria version), reusing the existing ContextPacket shape,
cases.ABSTAIN_ID/ABSTAIN_TEXT, and cases.MAX_OPTIONS check."""
from __future__ import annotations

from . import cases, relational_operators
from .context import ContextPacket
from .fields import DEFAULT_POLICY, Field, validate_source_and_candidates


def assemble_reader_packet(
    field: Field,
    source_id: str,
    operator: str,
    policy: str = DEFAULT_POLICY,
    criteria_version: str = relational_operators.DEFAULT_VERSION,
) -> ContextPacket:
    if criteria_version not in relational_operators.CRITERIA_BY_VERSION:
        raise ValueError(f"unknown criteria version: {criteria_version!r}")
    criteria = relational_operators.CRITERIA_BY_VERSION[criteria_version]
    if operator not in criteria:
        raise ValueError(f"unknown operator: {operator!r}; known: {relational_operators.OPERATOR_NAMES}")
    validate_source_and_candidates(field, source_id, policy)

    candidate_ids = field.eligible_candidate_ids(source_id, policy)
    options = {pid: field.manifest[pid].text for pid in candidate_ids}
    options[cases.ABSTAIN_ID] = cases.ABSTAIN_TEXT
    option_order = [*candidate_ids, cases.ABSTAIN_ID]
    excluded_neighbors = field.neighbors_of(source_id) if policy == "discovery" else {"previous": None, "next": None}

    return ContextPacket(
        case_id=f"reader-{field.id}-{source_id}-{operator.lower()}-{criteria_version}-{policy}",
        working_index="AGI",
        source_id=source_id,
        source_text=field.manifest[source_id].text,
        active_id=None,
        active_text=None,
        criterion=criteria[operator],
        options=options,
        option_order=option_order,
        reader_state={
            "app": "reader",
            "field": field.id,
            "active_page": source_id,
            "active_passage": None,
            "operator": operator,
            "policy": policy,
            "criteria_version": criteria_version,
            "excluded_neighbors": excluded_neighbors,
            "history": [],
        },
    )
