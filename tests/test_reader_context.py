import pytest

from gibsey_lab import cases, fields, relational_operators
from gibsey_lab.reader_context import assemble_reader_packet


def test_assembles_packet_with_exact_frozen_criterion():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "DEVELOP")
    assert packet.criterion == relational_operators.CRITERIA["DEVELOP"]
    assert packet.source_id == "PR1"
    assert packet.source_text == field.manifest["PR1"].text


def test_options_exclude_source_and_include_none():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "ECHO")
    assert "PR1" not in packet.options
    assert cases.ABSTAIN_ID in packet.options
    assert len(packet.options) == 21  # 20 other holdout pages + NONE


def test_rejects_unknown_operator():
    field = fields.load_field(fields.HOLDOUT_21)
    with pytest.raises(ValueError, match="unknown operator"):
        assemble_reader_packet(field, "PR1", "SOMETHING_ELSE")


def test_reader_state_records_field_and_operator_but_not_used_as_model_input():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "CONTRADICT")
    assert packet.reader_state["field"] == fields.HOLDOUT_21
    assert packet.reader_state["operator"] == "CONTRADICT"
    # The only text ever sent to the model is source_text/active_text/options -- never
    # reader_state, so history/session bookkeeping can never leak into a Jev request.
    assert packet.active_text is None
