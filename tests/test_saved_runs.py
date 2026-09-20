from gibsey_lab.saved_runs import find_saved_original_field_result


def test_finds_real_recorded_pr1_develop_result():
    """PR1/DEVELOP has a real Phase-A forward-field run on disk (destination PR4).
    Reads only -- makes no new call."""
    saved = find_saved_original_field_result("PR1", "DEVELOP")
    assert saved is not None
    assert saved.selected_id == "PR4"
    assert saved.field == "holdout-21"
    assert saved.returned_model == "jev-1.13.0"


def test_matches_only_the_canonical_original_field_run_not_diagnostic_or_tournament_runs():
    """PR1/DEVELOP also has separate saved runs from the removal-condition diagnostic
    (case_id prefix 'relop-holdout-diag-') and, for other sources, the tournament
    (prefix 'relop-holdout-tournament-'). Only the canonical 'relop-holdout-full-' run
    may ever be returned here."""
    saved = find_saved_original_field_result("PR1", "DEVELOP")
    assert saved is not None
    assert "relop-holdout-full-PR1-develop" in saved.run_dir.name
    assert "diag" not in saved.run_dir.name
    assert "tournament" not in saved.run_dir.name


def test_unknown_source_returns_none():
    saved = find_saved_original_field_result("ZZ99", "ECHO")
    assert saved is None
