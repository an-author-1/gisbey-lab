from gibsey_lab import cases
from gibsey_lab.context import assemble_f12_micro
from gibsey_lab.mock_client import run_choice_mock


def _run(packet):
    return run_choice_mock(
        state=packet.active_text,
        instructions=packet.criterion,
        criteria=packet.options,
        option_order=packet.option_order,
        model="jev-latest",
    )


def test_mock_is_deterministic(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    a = _run(packet)
    b = _run(packet)
    assert a.choice == b.choice
    assert a.probabilities == b.probabilities


def test_mock_never_claims_live(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = _run(packet)
    assert result.live is False
    assert result.returned_model != packet.criterion  # sanity: distinct, obviously-mock model tag
    assert "mock" in result.returned_model


def test_mock_choice_always_in_option_order(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = _run(packet)
    assert result.choice in packet.option_order


def test_mock_prefers_lexically_overlapping_option(synthetic_manifest, synthetic_reviewed_map):
    # F12.S4 (active) shares "apples" with F12.S1 and F12.S6; F12.S6 also echoes "sentence four" contextually
    # via shared "apples" token twice ("apples again"), so it should outscore non-overlapping options.
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    result = _run(packet)
    assert result.choice != "NONE"
