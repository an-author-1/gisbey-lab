import json

import pytest

from gibsey_lab.reviewing import ReviewError, update_review


def _make_run_dir(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    (run_dir / "review.json").write_text(json.dumps({
        "correspondence": None, "reading_effect": None,
        "grounding_score": None, "effect_score": None, "decision": "undecided",
    }))
    return run_dir


def test_update_review_partial_fields(tmp_path):
    run_dir = _make_run_dir(tmp_path)
    review = update_review(run_dir, decision="accept", grounding_score=2)
    assert review["decision"] == "accept"
    assert review["grounding_score"] == 2
    assert review["correspondence"] is None  # untouched fields stay pending

    on_disk = json.loads((run_dir / "review.json").read_text())
    assert on_disk == review


def test_missing_review_json_raises(tmp_path):
    run_dir = tmp_path / "no_review"
    run_dir.mkdir()
    with pytest.raises(ReviewError):
        update_review(run_dir, decision="reject")
