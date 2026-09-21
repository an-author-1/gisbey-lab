from gibsey_lab import relational_operators
from gibsey_lab.fields import HOLDOUT_21, load_field
from gibsey_lab.saved_runs import find_matching_recorded_result


def test_finds_real_recorded_pr1_develop_result():
    """PR1/DEVELOP has a real Phase-A forward-field run on disk (destination PR4).
    Reads only -- makes no new call."""
    from gibsey_lab.fields import INCLUDE_ADJACENT

    field = load_field(HOLDOUT_21)
    saved = find_matching_recorded_result(
        field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.1"]["DEVELOP"],
        expected_model="jev-latest", policy=INCLUDE_ADJACENT,
    )
    assert saved is not None
    assert saved.selected_id == "PR4"
    assert saved.field == "holdout-21"
    assert saved.returned_model == "jev-1.13.0"


def test_matches_only_the_canonical_original_field_run_not_diagnostic_or_tournament_runs():
    """PR1/DEVELOP also has separate saved runs from the removal-condition diagnostic
    (different candidate set/order) and, for other sources, the tournament (a restricted
    candidate set). Only a run whose full fingerprint matches the CURRENT holdout-21
    field for PR1/DEVELOP may ever be returned."""
    from gibsey_lab.fields import INCLUDE_ADJACENT

    field = load_field(HOLDOUT_21)
    saved = find_matching_recorded_result(
        field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.1"]["DEVELOP"],
        expected_model="jev-latest", policy=INCLUDE_ADJACENT,
    )
    assert saved is not None
    assert "diag" not in saved.run_dir.name
    assert "tournament" not in saved.run_dir.name


def test_unknown_source_returns_none():
    field = load_field(HOLDOUT_21)
    saved = find_matching_recorded_result(
        field, "PR1", "ECHO", "a criterion that was never actually used", expected_model="jev-latest"
    )
    assert saved is None


def test_wrong_model_configuration_does_not_match():
    """Same field/source/operator/criterion/policy, but a model that was never actually
    requested for this pair -- must not be treated as a valid recorded result. Policy is
    pinned to INCLUDE_ADJACENT (what the real historical run used) so model is the only
    varying factor."""
    from gibsey_lab.fields import INCLUDE_ADJACENT

    field = load_field(HOLDOUT_21)
    saved = find_matching_recorded_result(
        field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.1"]["DEVELOP"],
        expected_model="some-other-model", policy=INCLUDE_ADJACENT,
    )
    assert saved is None


def test_changed_source_text_invalidates_reuse():
    """If the source page's content has changed since a run was recorded, its hash no
    longer matches, so that run must not be reused -- 'candidate versions' means exact
    content, not just the same ID. Policy pinned to INCLUDE_ADJACENT so the hash mismatch
    is the only varying factor."""
    import dataclasses

    from gibsey_lab.fields import INCLUDE_ADJACENT

    field = load_field(HOLDOUT_21)
    edited_page = dataclasses.replace(field.manifest["PR1"], text="this is not the real PR1 text", sha256="0" * 64)
    edited_manifest = {**field.manifest, "PR1": edited_page}
    edited_field = dataclasses.replace(field, manifest=edited_manifest)

    saved = find_matching_recorded_result(
        edited_field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.1"]["DEVELOP"],
        expected_model="jev-latest", policy=INCLUDE_ADJACENT,
    )
    assert saved is None


def test_full_41_field_surfaces_no_v0_2_result_without_a_recorded_run(tmp_path):
    """Nothing is surfaced as 'recorded' for a criterion that no run in the searched
    directory used. (This originally asserted against the real runs/ directory, which was
    true until the reader produced live v0.2 runs on 2026-09-20; it now uses an isolated
    runs dir so real reading sessions cannot break it.)"""
    from gibsey_lab.fields import FULL_41

    field = load_field(FULL_41)
    saved = find_matching_recorded_result(
        field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.2"]["DEVELOP"],
        expected_model="jev-latest", runs_dir=tmp_path,
    )
    assert saved is None


def test_discovery_policy_does_not_match_a_run_recorded_under_include_adjacent():
    """A real reader-produced run exists for full-41/PR1/DEVELOP (v0.1, made before the
    Discovery policy existed, so its candidate set is unrestricted -- equivalent to
    include-adjacent). A Discovery-policy query for the same field/source/operator/
    criterion must not match it, since Discovery's candidate set is strictly smaller."""
    from gibsey_lab.fields import DISCOVERY, FULL_41

    field = load_field(FULL_41)
    saved = find_matching_recorded_result(
        field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.1"]["DEVELOP"],
        expected_model="jev-latest", policy=DISCOVERY,
    )
    assert saved is None


def test_include_adjacent_policy_matches_the_real_historical_run():
    """The same query, but with the policy the run was actually made under, does match."""
    from gibsey_lab.fields import FULL_41, INCLUDE_ADJACENT

    field = load_field(FULL_41)
    saved = find_matching_recorded_result(
        field, "PR1", "DEVELOP", relational_operators.CRITERIA_BY_VERSION["v0.1"]["DEVELOP"],
        expected_model="jev-latest", policy=INCLUDE_ADJACENT,
    )
    assert saved is not None
    assert saved.selected_id == "PR2"
