from gibsey_lab.corpus import EXPECTED_IDS, load_manifest, validate_manifest


def test_real_manifest_has_all_twenty_ids():
    manifest = load_manifest()
    assert set(manifest.keys()) == set(EXPECTED_IDS)


def test_real_corpus_has_no_current_problems():
    # Documents present state: all twenty pages are non-empty, no duplicates/missing.
    manifest = load_manifest()
    assert validate_manifest(manifest) == []


def test_hash_matches_raw_file_bytes():
    import hashlib

    manifest = load_manifest()
    page = manifest["F12"]
    raw = page.path.read_bytes()
    assert page.sha256 == hashlib.sha256(raw).hexdigest()


def test_non_corpus_files_are_excluded():
    manifest = load_manifest()
    # .obsidian/ lives outside the two scanned folders and must never surface as a page id.
    assert ".obsidian" not in manifest
    assert all(pid[0] in ("P", "F") for pid in manifest)


def test_validate_manifest_flags_missing_and_empty_pages(synthetic_manifest):
    manifest = dict(synthetic_manifest)
    del manifest["P3"]  # missing
    empty_page = manifest["F5"]
    manifest["F5"] = type(empty_page)(id="F5", path=empty_page.path, text="   \n", sha256="x", order=5)  # empty

    problems = validate_manifest(manifest)
    assert "missing page: P3" in problems
    assert any(p.startswith("empty page: F5") for p in problems)
    assert not any("F1" in p or "P1" in p for p in problems)
