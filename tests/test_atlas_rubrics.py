from __future__ import annotations

import re

import pytest

from gibsey_lab import scoring
from gibsey_lab.atlas import rubrics
from gibsey_lab.fields import EXPECTED_FULL_41_IDS

# Wording is frozen per version: live records exist under these exact hashes.
V1_SHA256 = "662ecfb57f8392980919fde8988b9e72b211a6816b04111632265726290d80cb"
V2_SHA256 = "a1a93f0176f7d456ace427bec5432c7952d348d6e12f571e74ef408d046485a9"
ALL_VERSIONS = ["atlas-rubric-v1", "atlas-rubric-v2"]

CONTRACT_DIMENSIONS = (
    "direct_q_fit", "echo", "development", "contradiction", "bridge_relation", "redundancy", "missing_context",
)


def _all_model_visible_text(rubric) -> list[str]:
    return [t for q in rubric.questions for t in (q.instructions, *q.levels)]


def test_dimensions_are_the_contract_ids_in_fixed_order():
    assert rubrics.DIMENSIONS == CONTRACT_DIMENSIONS
    assert rubrics.RUBRIC_VERSION == "atlas-rubric-v2"
    assert rubrics.get_rubric() is rubrics.RUBRIC_V2 is rubrics.RUBRICS_BY_VERSION["atlas-rubric-v2"]
    assert sorted(rubrics.RUBRICS_BY_VERSION) == ALL_VERSIONS
    for version in ALL_VERSIONS:
        assert rubrics.get_rubric(version).dimensions == CONTRACT_DIMENSIONS


def test_registered_versions_are_frozen_and_v1_stays_retrievable_unchanged():
    assert rubrics.get_rubric("atlas-rubric-v1") is rubrics.RUBRIC_V1
    assert rubrics.RUBRIC_V1.sha256 == V1_SHA256
    assert rubrics.RUBRIC_V2.sha256 == V2_SHA256


def test_v2_differs_from_v1_only_in_bridge_relation():
    for old, new in zip(rubrics.RUBRIC_V1.questions, rubrics.RUBRIC_V2.questions):
        if old.qid == "bridge_relation":
            assert old.instructions != new.instructions and all(a != b for a, b in zip(old.levels, new.levels))
        else:
            assert old == new
    v1_request = rubrics.build_pair_request("a", "b", "m", rubric_version="atlas-rubric-v1")
    assert v1_request.questions == rubrics.RUBRIC_V1.questions
    assert v1_request.request_sha256() != rubrics.build_pair_request("a", "b", "m").request_sha256()


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_every_question_names_both_role_keys_and_the_direction_and_has_four_levels(version):
    for q in rubrics.get_rubric(version).questions:
        assert "source_page" in q.instructions and "destination_page" in q.instructions
        assert "destination_page AFTER source_page" in q.instructions
        assert "reverse" in q.instructions  # the opposite direction is explicitly not being asked
        assert len(q.levels) == 4
        assert len(set(q.levels)) == 4


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_no_model_visible_text_mentions_page_ids_order_or_interestingness(version):
    page_id = re.compile(r"\b(?:P|F|LF|PR)\d{1,2}\b")
    banned = re.compile(r"interesting|authored|page ids?\b|page number|adjacent|neighbou?r|next page|previous page", re.I)
    for text in _all_model_visible_text(rubrics.get_rubric(version)):
        assert not page_id.search(text), text
        assert not banned.search(text), text
        for pid in EXPECTED_FULL_41_IDS:
            assert not re.search(rf"\b{pid}\b", text)


@pytest.mark.parametrize("dimension", ["development", "contradiction"])
def test_shared_topic_alone_cannot_reach_the_upper_levels(dimension):
    q = rubrics.get_rubric().question(dimension)
    # Shared subject is explicitly parked in the lower levels ...
    assert re.search(r"subject|topic", q.levels[0] + q.levels[1])
    assert "lower levels" in q.instructions
    # ... and both upper levels require engagement with something specific in the source.
    for level in q.levels[2:]:
        assert "specific" in level and "source_page" in level


def test_echo_and_redundancy_are_separable_and_may_both_be_high():
    echo = rubrics.get_rubric().question("echo")
    redundancy = rubrics.get_rubric().question("redundancy")
    for level in echo.levels[2:]:
        assert re.search(r"phrase, image, structure, or claim", level)
    assert "do not lower the level because the passages overlap heavily" in echo.instructions
    assert "how little does destination_page add" in redundancy.instructions
    assert "not about whether a particular phrase or image recurs" in redundancy.instructions
    assert "nothing new" in redundancy.levels[3]


@pytest.mark.parametrize("version", ALL_VERSIONS)
def test_bridge_is_a_relation_between_the_two_passages_not_a_generated_page(version):
    bridge = rubrics.get_rubric(version).question("bridge_relation")
    assert "does not concern any third, linking, or newly written passage" in bridge.instructions
    assert "nothing is to be written" in bridge.instructions
    assert "shared vocabulary" in bridge.levels[1]  # shared words alone stay low


def test_v2_bridge_decides_sameness_first_and_requires_both_differences():
    bridge = rubrics.RUBRIC_V2.question("bridge_relation")
    assert "First decide whether the two passages share the same speaker or characters" in bridge.instructions
    # Level 0 is only "nothing to bridge" -- no longer also "different but unconnected".
    assert bridge.levels[0].startswith("Nothing to bridge:") and "differ" not in bridge.levels[0].replace("difference", "")
    assert "however closely related they are" in bridge.levels[0]
    for level in bridge.levels[1:]:  # a difference in speaker/characters AND situation, not either/or
        assert "differ in speaker or characters and in situation" in level
    assert "only holds when stated very abstractly" in bridge.levels[1]
    for level in bridge.levels[2:]:
        assert "specific connection" in level and "what each passage is doing" in level


def test_missing_context_high_means_neither_page_supplies_it():
    q = rubrics.get_rubric().question("missing_context")
    assert "NEITHER" in q.instructions
    assert "neither passage supplies" in q.levels[3]
    assert "Material that source_page does supply is not missing" in q.instructions


def test_direct_q_fit_is_one_step_with_no_intermediary():
    q = rubrics.get_rubric().question("direct_q_fit")
    assert "nothing read in between" in q.instructions
    assert "no intermediate passage needed" in q.levels[3]


def test_build_pair_request_state_holds_only_the_two_texts_under_role_keys():
    request = rubrics.build_pair_request("first text", "second text", "jev-latest")
    assert request.kind == "base_pair"
    assert request.state == {"source_page": {"text": "first text"}, "destination_page": {"text": "second text"}}
    assert [q.qid for q in request.questions] == list(CONTRACT_DIMENSIONS)
    assert request.requested_model == "jev-latest"
    assert {k: list(v) for k, v in request.state.items()} == rubrics.STATE_LAYOUT


def test_direction_changes_the_request_and_mock_answers_validate():
    forward = rubrics.build_pair_request("alpha text", "beta text", "m")
    backward = rubrics.build_pair_request("beta text", "alpha text", "m")
    assert forward.request_sha256() != backward.request_sha256()
    outcome = scoring.mock_dispatch(forward)
    assert outcome.status == "ok" and set(outcome.answers) == set(CONTRACT_DIMENSIONS)


def test_unknown_rubric_version_is_refused_and_registry_allows_new_versions(monkeypatch):
    with pytest.raises(KeyError):
        rubrics.get_rubric("atlas-rubric-v0")
    v1_hash = rubrics.RUBRIC_V1.sha256
    v3 = rubrics.Rubric(version="atlas-rubric-v3-test", questions=rubrics.RUBRIC_V1.questions)
    monkeypatch.setitem(rubrics.RUBRICS_BY_VERSION, v3.version, v3)
    assert rubrics.get_rubric(v3.version) is v3
    assert rubrics.RUBRIC_V1.sha256 == v1_hash and v3.sha256 != v1_hash
