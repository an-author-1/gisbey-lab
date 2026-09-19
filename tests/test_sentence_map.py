from gibsey_lab.corpus import Page
from gibsey_lab.sentence_map import propose_sentence_map


def test_propose_on_empty_page_is_blocked(tmp_path):
    page = Page(id="F9", path=tmp_path / "F9.md", text="   ", sha256="x", order=9)
    sm = propose_sentence_map(page)
    assert sm.status == "blocked"
    assert sm.sentences == {}


def test_propose_splits_on_blank_lines(synthetic_f12):
    sm = propose_sentence_map(synthetic_f12)
    assert sm.status == "proposed"
    assert list(sm.sentences) == [f"F12.S{i}" for i in range(1, 10)]
    assert sm.sentences["F12.S4"] == "Sentence four, the active one, about grapes and apples."


def test_propose_records_source_hash(synthetic_f12):
    sm = propose_sentence_map(synthetic_f12)
    assert sm.source_sha256 == synthetic_f12.sha256


def test_real_f12_sentence_boundaries_and_text_are_exact():
    """Regression check: pins all nine real F12 sentences against their exact authored
    text, word-for-word, to catch any future splitting/whitespace regression (e.g. an
    internal space silently dropped, as was reported — though not reproduced — for S3)."""
    from gibsey_lab.corpus import load_manifest

    manifest = load_manifest()
    sm = propose_sentence_map(manifest["F12"])

    assert list(sm.sentences) == [f"F12.S{i}" for i in range(1, 10)]
    assert sm.sentences == {
        "F12.S1": "Return to texts often.",
        "F12.S2": "Re-ride attractions.",
        "F12.S3": "Don’t forget that this novel and demo is a theme park, but it is a new kind of theme park.",
        "F12.S4": "You are both the Imaginator constructing the rides as you ride them, as well as the park goer who rides them.",
        "F12.S5": "As such, proceed with caution, both within your AGI and Gibsey Vault.",
        "F12.S6": (
            "Every choice you make, every directional queue, monologic prompt, dialogic "
            "generation, and hologic transition you select transforms the past, present, "
            "and future in real time, as it always has, and ever will."
        ),
        "F12.S7": (
            "Gibsey has been structured in previous forms, in this form, and the forms it "
            "will take in the future, to better visualize and participate in that creative, "
            "constructive, reconstructive, and deconstructive process."
        ),
        "F12.S8": (
            "As is stated before nearly every attraction begins at Gibsey World, always "
            "keep in mind the stirring edict included below."
        ),
        "F12.S9": (
            "Keep your hands, arms, feet, and legs inside the vehicle at all times, and "
            "enjoy your stay at The Wonderful Worlds of Gibsey."
        ),
    }
    assert "  " not in sm.sentences["F12.S3"]  # no doubled space
    assert "itis" not in sm.sentences["F12.S3"]  # no dropped space
