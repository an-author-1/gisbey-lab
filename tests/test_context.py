import pytest

from gibsey_lab import cases
from gibsey_lab.context import CaseError, assemble_f12_macro, assemble_f12_micro
from gibsey_lab.corpus import Page
from gibsey_lab.sentence_map import SentenceMap


def test_micro_eligibility_excludes_active_and_neighbors(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    assert set(packet.option_order) == {"F12.S1", "F12.S2", "F12.S6", "F12.S7", "F12.S8", "F12.S9", "NONE"}
    assert "F12.S4" not in packet.options  # active
    assert "F12.S3" not in packet.options  # neighbor
    assert "F12.S5" not in packet.options  # neighbor
    assert packet.active_id == "F12.S4"
    assert packet.active_text == synthetic_reviewed_map.sentences["F12.S4"]


def test_micro_option_text_is_exact_source_text(synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    for sid in cases.MICRO_ELIGIBLE_IDS:
        assert packet.options[sid] == synthetic_reviewed_map.sentences[sid]


def test_micro_requires_reviewed_map_not_proposed(synthetic_manifest, synthetic_reviewed_map):
    proposed = SentenceMap(
        page_id="F12", source_sha256=synthetic_reviewed_map.source_sha256,
        sentences=synthetic_reviewed_map.sentences, status="proposed",
    )
    with pytest.raises(CaseError, match="reviewed"):
        assemble_f12_micro(synthetic_manifest, proposed)


def test_micro_rejects_stale_map_after_source_edit(synthetic_manifest, synthetic_reviewed_map):
    stale = SentenceMap(
        page_id="F12", source_sha256="not-the-current-hash",
        sentences=synthetic_reviewed_map.sentences, status="reviewed",
    )
    with pytest.raises(CaseError, match="does not match"):
        assemble_f12_micro(synthetic_manifest, stale)


def test_micro_refuses_empty_source(synthetic_manifest, synthetic_reviewed_map, tmp_path):
    manifest = dict(synthetic_manifest)
    manifest["F12"] = Page(id="F12", path=tmp_path / "F12.md", text="", sha256="e" * 64, order=12)
    with pytest.raises(CaseError, match="empty"):
        assemble_f12_micro(manifest, synthetic_reviewed_map)


def test_macro_excludes_source_and_includes_all_others(synthetic_manifest):
    packet = assemble_f12_macro(synthetic_manifest)
    assert "F12" not in packet.options
    assert set(packet.option_order) == (set(synthetic_manifest) - {"F12"}) | {"NONE"}
    assert len(packet.option_order) == 20  # 19 candidates + NONE


def test_macro_option_text_is_exact_page_text(synthetic_manifest):
    packet = assemble_f12_macro(synthetic_manifest)
    assert packet.options["F1"] == synthetic_manifest["F1"].text


def test_macro_refuses_when_any_candidate_empty(synthetic_manifest, tmp_path):
    manifest = dict(synthetic_manifest)
    manifest["P4"] = Page(id="P4", path=tmp_path / "P4.md", text="", sha256="e" * 64, order=4)
    with pytest.raises(CaseError, match="empty"):
        assemble_f12_macro(manifest)


def test_macro_refuses_empty_source(synthetic_manifest, tmp_path):
    manifest = dict(synthetic_manifest)
    manifest["F12"] = Page(id="F12", path=tmp_path / "F12.md", text="", sha256="e" * 64, order=12)
    with pytest.raises(CaseError, match="empty"):
        assemble_f12_macro(manifest)


def test_real_f12_micro_currently_blocked_pending_review():
    """Documents the live blocker: the corpus is complete, but the F12 sentence mapping
    is still 'proposed', not 'reviewed', so the micro case correctly refuses to run."""
    from gibsey_lab.corpus import load_manifest
    from gibsey_lab.sentence_map import load_reviewed_map

    manifest = load_manifest()
    reviewed = load_reviewed_map(manifest["F12"])
    if reviewed is not None:
        pytest.skip("F12 sentence mapping has since been reviewed; blocker no longer applies")
    with pytest.raises(CaseError, match="reviewed"):
        assemble_f12_micro(manifest, reviewed)


def test_real_f12_macro_is_buildable():
    """Documents that with all twenty pages populated, the macro case (which needs no
    sentence mapping) is buildable right now."""
    from gibsey_lab.corpus import load_manifest

    manifest = load_manifest()
    packet = assemble_f12_macro(manifest)
    assert len(packet.option_order) == 20
    assert "NONE" in packet.options
