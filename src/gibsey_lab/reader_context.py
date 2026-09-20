"""Context assembly for the reader app: builds a ContextPacket for (field, source,
operator) using the frozen Q Operator Prototype v0.1 wording, reusing the existing
ContextPacket shape, cases.ABSTAIN_ID/ABSTAIN_TEXT, and cases.MAX_OPTIONS check."""
from __future__ import annotations

from . import cases, relational_operators
from .context import ContextPacket
from .fields import Field, validate_source_and_candidates


def assemble_reader_packet(field: Field, source_id: str, operator: str) -> ContextPacket:
    if operator not in relational_operators.CRITERIA:
        raise ValueError(f"unknown operator: {operator!r}; known: {relational_operators.OPERATOR_NAMES}")
    validate_source_and_candidates(field, source_id)

    candidate_ids = field.candidate_ids_for(source_id)
    options = {pid: field.manifest[pid].text for pid in candidate_ids}
    options[cases.ABSTAIN_ID] = cases.ABSTAIN_TEXT
    option_order = [*candidate_ids, cases.ABSTAIN_ID]

    return ContextPacket(
        case_id=f"reader-{field.id}-{source_id}-{operator.lower()}",
        working_index="AGI",
        source_id=source_id,
        source_text=field.manifest[source_id].text,
        active_id=None,
        active_text=None,
        criterion=relational_operators.CRITERIA[operator],
        options=options,
        option_order=option_order,
        reader_state={
            "app": "reader",
            "field": field.id,
            "active_page": source_id,
            "active_passage": None,
            "operator": operator,
            "history": [],
        },
    )
