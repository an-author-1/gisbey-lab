import pytest

from gibsey_lab.context import assemble_f12_micro
from gibsey_lab.results import ChoiceResult
from gibsey_lab.validate import ProviderResultError, validate_choice_result


def test_valid_choice_resolves_to_exact_source_text(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = ChoiceResult(
        requested_model="jev-latest", returned_model="jev-latest-x", choice="F12.S6",
        confidence=0.8, probabilities={"F12.S6": 0.8, "NONE": 0.2}, live=True,
    )
    outcome = validate_choice_result(packet, result)
    assert outcome.selected_id == "F12.S6"
    assert outcome.selected_text == packet.options["F12.S6"]
    assert outcome.is_abstention is False


def test_none_choice_is_abstention(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = ChoiceResult(
        requested_model="jev-latest", returned_model="jev-latest-x", choice="NONE",
        confidence=0.4, probabilities={"NONE": 0.4}, live=True,
    )
    outcome = validate_choice_result(packet, result)
    assert outcome.is_abstention is True
    assert outcome.selected_id is None
    assert outcome.selected_text is None


def test_rejects_choice_outside_permitted_set(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = ChoiceResult(
        requested_model="jev-latest", returned_model="jev-latest-x", choice="F12.S4",  # active, not eligible
        confidence=0.9, probabilities={"F12.S4": 0.9}, live=True,
    )
    with pytest.raises(ProviderResultError):
        validate_choice_result(packet, result)


def test_rejects_probabilities_referencing_unknown_options(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = ChoiceResult(
        requested_model="jev-latest", returned_model="jev-latest-x", choice="F12.S6",
        confidence=0.5, probabilities={"F12.S6": 0.5, "F99.S1": 0.5}, live=True,
    )
    with pytest.raises(ProviderResultError):
        validate_choice_result(packet, result)
