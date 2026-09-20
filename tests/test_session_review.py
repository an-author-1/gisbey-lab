import json

from gibsey_lab.session_review import gather_recent_traversal_material


def _make_run(run_dir, source_id, destination_id, criterion, field_id, operator):
    run_dir.mkdir(parents=True)
    (run_dir / "input.json").write_text(json.dumps({
        "run_id": run_dir.name,
        "source_id": source_id,
        "criterion": criterion,
        "options": {destination_id: f"exact text of {destination_id}"},
        "corpus_hashes": {source_id: "not-a-real-hash"},
        "reader_state": {"field": field_id, "operator": operator},
    }))


def test_gathers_material_without_confidence_and_labels_hash_mismatch(tmp_path):
    log_path = tmp_path / "session_log.jsonl"
    run_dir = tmp_path / "runs" / "run1"
    _make_run(run_dir, "PR1", "PR4", "a criterion", "holdout-21", "DEVELOP")

    with open(log_path, "a") as f:
        f.write(json.dumps({
            "event": "accept_and_follow", "at": "2026-01-01T00:00:00Z",
            "field": "holdout-21", "source": "PR1", "operator": "DEVELOP",
            "destination": "PR4", "run_dir": str(run_dir),
            "proposal_id": "prop_x", "bond_id": "bond_x",
        }) + "\n")

    material = gather_recent_traversal_material(limit=10, log_path=log_path)
    assert len(material) == 1
    item = material[0]
    assert item["destination_text"] == "exact text of PR4"
    assert item["criterion"] == "a criterion"
    # The fake hash never matches a real page's sha256, so source text is correctly
    # withheld rather than silently guessed at.
    assert item["source_text"] is None
    assert item["source_hash_verified"] is False
    assert "confidence" not in item
    assert "probabilities" not in item


def test_ignores_missing_run_dirs():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        tmp_path = Path(tmp)
        log_path = tmp_path / "session_log.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps({
                "event": "accept_and_follow", "at": "2026-01-01T00:00:00Z",
                "field": "holdout-21", "source": "PR1", "operator": "ECHO",
                "destination": "PR2", "run_dir": str(tmp_path / "missing_run"),
            }) + "\n")
        material = gather_recent_traversal_material(limit=10, log_path=log_path)
        assert material == []  # references a nonexistent run dir -- not usable


def test_respects_limit(tmp_path):
    log_path = tmp_path / "session_log.jsonl"
    with open(log_path, "a") as f:
        for i in range(3):
            run_dir = tmp_path / "runs" / f"run{i}"
            _make_run(run_dir, "PR1", "PR2", f"criterion {i}", "holdout-21", "ECHO")
            f.write(json.dumps({
                "event": "accept_and_follow", "at": f"2026-01-0{i+1}T00:00:00Z",
                "field": "holdout-21", "source": "PR1", "operator": "ECHO",
                "destination": "PR2", "run_dir": str(run_dir),
            }) + "\n")

    material = gather_recent_traversal_material(limit=2, log_path=log_path)
    assert len(material) == 2
    assert material[-1]["criterion"] == "criterion 2"  # most recent kept


def test_empty_log_returns_empty_list(tmp_path):
    assert gather_recent_traversal_material(limit=10, log_path=tmp_path / "no_such_log.jsonl") == []
