import pytest

from gibsey_lab import cases, fields, relational_operators
from gibsey_lab.reader_context import assemble_reader_packet


def test_assembles_packet_with_exact_active_criterion():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "DEVELOP")
    assert packet.criterion == relational_operators.CRITERIA["DEVELOP"]
    assert packet.criterion == relational_operators.V0_2_CRITERIA["DEVELOP"]  # default version is v0.2
    assert packet.source_id == "PR1"
    assert packet.source_text == field.manifest["PR1"].text


def test_can_request_a_specific_criteria_version_explicitly():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "DEVELOP", criteria_version="v0.1")
    assert packet.criterion == relational_operators.V0_1_CRITERIA["DEVELOP"]
    assert packet.criterion != relational_operators.V0_2_CRITERIA["DEVELOP"]


def test_options_exclude_source_and_include_none_under_include_adjacent():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "ECHO", policy=fields.INCLUDE_ADJACENT)
    assert "PR1" not in packet.options
    assert cases.ABSTAIN_ID in packet.options
    assert len(packet.options) == 21  # 20 other holdout pages + NONE, nothing excluded


def test_discovery_is_the_default_policy_and_excludes_only_the_successor_for_a_first_page():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "ECHO")  # policy defaults to discovery
    assert packet.reader_state["policy"] == "discovery"
    assert "PR2" not in packet.options  # PR1's immediate successor
    assert "PR1" not in packet.options  # the source itself
    assert len(packet.options) == 20  # 19 remaining holdout pages + NONE
    assert packet.reader_state["excluded_neighbors"] == {"previous": None, "next": "PR2"}


def test_discovery_excludes_both_neighbors_for_a_middle_page():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "LF6", "DEVELOP")
    assert "LF5" not in packet.options
    assert "LF7" not in packet.options
    assert packet.reader_state["excluded_neighbors"] == {"previous": "LF5", "next": "LF7"}


def test_discovery_never_treats_text_boundaries_as_adjacency():
    """P8 is the last page of 'an author's preface'; its successor must not resolve to
    F1 just because F1 happens to load right after P8 in some other ordering."""
    field = fields.load_field(fields.FULL_41)
    packet = assemble_reader_packet(field, "P8", "ECHO")
    assert packet.reader_state["excluded_neighbors"] == {"previous": "P7", "next": None}
    assert "F1" in packet.options  # not excluded -- no cross-text adjacency


def test_rejects_unknown_operator():
    field = fields.load_field(fields.HOLDOUT_21)
    with pytest.raises(ValueError, match="unknown operator"):
        assemble_reader_packet(field, "PR1", "SOMETHING_ELSE")


def test_rejects_unknown_criteria_version():
    field = fields.load_field(fields.HOLDOUT_21)
    with pytest.raises(ValueError, match="unknown criteria version"):
        assemble_reader_packet(field, "PR1", "ECHO", criteria_version="v9.9")


def test_reader_state_records_field_operator_policy_and_version_but_not_used_as_model_input():
    field = fields.load_field(fields.HOLDOUT_21)
    packet = assemble_reader_packet(field, "PR1", "CONTRADICT")
    assert packet.reader_state["field"] == fields.HOLDOUT_21
    assert packet.reader_state["operator"] == "CONTRADICT"
    assert packet.reader_state["policy"] == "discovery"
    assert packet.reader_state["criteria_version"] == "v0.2"
    # The only text ever sent to the model is source_text/active_text/options -- never
    # reader_state, so history/session bookkeeping can never leak into a Jev request.
    assert packet.active_text is None
