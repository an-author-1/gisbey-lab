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
