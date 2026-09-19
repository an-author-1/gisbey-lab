import hashlib
from pathlib import Path

import pytest

from gibsey_lab.corpus import Page
from gibsey_lab.sentence_map import SentenceMap


def make_page(page_id: str, text: str, order: int, path: Path) -> Page:
    return Page(id=page_id, path=path, text=text, sha256=hashlib.sha256(text.encode()).hexdigest(), order=order)


@pytest.fixture
def synthetic_f12(tmp_path) -> Page:
    text = "\n\n".join(
        [
            "Sentence one about apples.",
            "Sentence two about oranges.",
            "Sentence three about pears.",
            "Sentence four, the active one, about grapes and apples.",
            "Sentence five about plums.",
            "Sentence six about apples again, echoing sentence four.",
            "Sentence seven about kiwis.",
            "Sentence eight about mangoes.",
            "Sentence nine about lemons.",
        ]
    )
    return make_page("F12", text, 12, tmp_path / "F12.md")


@pytest.fixture
def synthetic_reviewed_map(synthetic_f12) -> SentenceMap:
    parts = synthetic_f12.text.split("\n\n")
    sentences = {f"F12.S{i}": t for i, t in enumerate(parts, start=1)}
    return SentenceMap(page_id="F12", source_sha256=synthetic_f12.sha256, sentences=sentences, status="reviewed")


@pytest.fixture
def synthetic_manifest(tmp_path, synthetic_f12) -> dict:
    manifest = {"F12": synthetic_f12}
    for i in range(1, 13):
        if i == 12:
            continue
        manifest[f"F{i}"] = make_page(f"F{i}", f"Foreword page {i} body text.", i, tmp_path / f"F{i}.md")
    for i in range(1, 9):
        manifest[f"P{i}"] = make_page(f"P{i}", f"Preface page {i} body text.", i, tmp_path / f"P{i}.md")
    return manifest
