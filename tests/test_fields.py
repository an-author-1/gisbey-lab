import pytest

from gibsey_lab import fields


def test_holdout_field_has_21_pages():
    field = fields.load_field(fields.HOLDOUT_21)
    assert len(field.manifest) == 21
    assert "PR1" in field.manifest and "LF1" in field.manifest


def test_full_field_has_41_pages_no_overlap():
    field = fields.load_field(fields.FULL_41)
    assert len(field.manifest) == 41
    ids = set(field.manifest)
    assert {"P1", "F1", "LF1", "PR1"} <= ids


def test_unknown_field_raises():
    with pytest.raises(fields.FieldError, match="unknown field"):
        fields.load_field("not-a-real-field")


def test_candidate_ids_exclude_source_and_are_canonical():
    field = fields.load_field(fields.HOLDOUT_21)
    candidates = field.candidate_ids_for("PR1")
    assert "PR1" not in candidates
    assert len(candidates) == 20
    assert candidates[0] == "LF1"  # canonical order: LF before PR


def test_validate_rejects_unknown_source():
    field = fields.load_field(fields.HOLDOUT_21)
    with pytest.raises(fields.FieldError, match="not eligible"):
        fields.validate_source_and_candidates(field, "P1")  # P1 is training-corpus only


def test_validate_accepts_known_source():
    field = fields.load_field(fields.HOLDOUT_21)
    fields.validate_source_and_candidates(field, "PR1")  # should not raise


def test_full_field_all_ids_handles_mixed_prefix_lengths():
    """Regression: single-letter (P1, F12) and two-letter (LF16, PR5) IDs must sort
    together without crashing -- a fixed pid[:2] slice breaks on single-letter IDs
    because int(pid[2:]) becomes int('')."""
    field = fields.load_field(fields.FULL_41)
    ids = field.all_ids()
    assert len(ids) == 41
    assert len(set(ids)) == 41
    assert "P1" in ids and "F12" in ids and "LF16" in ids and "PR5" in ids


def test_full_field_candidates_for_training_source_include_holdout_pages():
    field = fields.load_field(fields.FULL_41)
    candidates = field.candidate_ids_for("P1")
    assert "P1" not in candidates
    assert len(candidates) == 40
    assert "LF1" in candidates and "F1" in candidates
