from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .corpus import REPO_ROOT, Page

DATA_DIR = REPO_ROOT / "data"

# Sentences are blank-line-delimited paragraphs in the authored source; the vault's own
# prose convention (one sentence per paragraph in F12) makes this segmentation exact
# rather than heuristic, but it still requires explicit human review before use.
_SENTENCE_SPLIT = re.compile(r"\n\s*\n")


class SentenceMapError(Exception):
    pass


@dataclass(frozen=True)
class SentenceMap:
    page_id: str
    source_sha256: str
    sentences: dict[str, str]
    status: str  # "blocked" (source empty) | "proposed" | "reviewed"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"


def _path_for(page_id: str) -> Path:
    return DATA_DIR / f"sentence_map.{page_id}.json"


def propose_sentence_map(page: Page) -> SentenceMap:
    if page.is_empty:
        return SentenceMap(page_id=page.id, source_sha256=page.sha256, sentences={}, status="blocked")
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(page.text.strip()) if p.strip()]
    sentences = {f"{page.id}.S{i}": text for i, text in enumerate(parts, start=1)}
    return SentenceMap(page_id=page.id, source_sha256=page.sha256, sentences=sentences, status="proposed")


def save_map(sm: SentenceMap) -> Path:
    path = _path_for(sm.page_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sm.to_json())
    return path


def load_map(page_id: str) -> SentenceMap | None:
    path = _path_for(page_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return SentenceMap(**data)


def load_reviewed_map(page: Page) -> SentenceMap | None:
    """Return the stored map only if it's marked reviewed and still matches the current
    source text. A source edit after review silently invalidates it rather than reusing
    a stale mapping."""
    sm = load_map(page.id)
    if sm is None or sm.status != "reviewed":
        return None
    if sm.source_sha256 != page.sha256:
        return None
    return sm


def approve(page: Page) -> SentenceMap:
    sm = load_map(page.id)
    if sm is None:
        raise SentenceMapError(f"no proposed mapping on disk for {page.id}; run propose-sentence-map first")
    if sm.source_sha256 != page.sha256:
        raise SentenceMapError(
            f"stored mapping for {page.id} was proposed against a different source version "
            f"(stored sha256={sm.source_sha256[:12]}..., current sha256={page.sha256[:12]}...); "
            "re-run propose-sentence-map before approving"
        )
    if sm.status == "blocked":
        raise SentenceMapError(f"cannot approve: source page {page.id} is empty")
    reviewed = SentenceMap(page_id=sm.page_id, source_sha256=sm.source_sha256, sentences=sm.sentences, status="reviewed")
    save_map(reviewed)
    return reviewed
