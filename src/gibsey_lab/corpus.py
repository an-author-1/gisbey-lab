from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_DIR = REPO_ROOT / "vault"
PREFACE_DIR = VAULT_DIR / "an author's preface"
FOREWORD_DIR = VAULT_DIR / "The Foreword to the Foreword to an author's preface"

ID_PATTERN = re.compile(r"^(P|F)(\d{1,2})$")

EXPECTED_PREFACE_IDS = [f"P{i}" for i in range(1, 9)]
EXPECTED_FOREWORD_IDS = [f"F{i}" for i in range(1, 13)]
EXPECTED_IDS = EXPECTED_PREFACE_IDS + EXPECTED_FOREWORD_IDS


class CorpusError(Exception):
    pass


@dataclass(frozen=True)
class Page:
    id: str
    path: Path
    text: str
    sha256: str
    order: int

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) == 0


def _load_dir(dir_path: Path, prefix: str) -> dict[str, Page]:
    if not dir_path.is_dir():
        raise CorpusError(f"expected corpus folder not found: {dir_path}")
    pages: dict[str, Page] = {}
    for f in sorted(dir_path.glob("*.md")):
        match = ID_PATTERN.match(f.stem)
        if not match or match.group(1) != prefix:
            # Excludes non-corpus material (Obsidian config, templates, stray notes).
            continue
        page_id = f.stem
        if page_id in pages:
            raise CorpusError(f"duplicate page id: {page_id} ({f})")
        text = f.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        pages[page_id] = Page(id=page_id, path=f, text=text, sha256=digest, order=int(match.group(2)))
    return pages


def load_manifest() -> dict[str, Page]:
    """Load the twenty authored pages. Obsidian config (.obsidian/) is outside these two
    folders and is never scanned; files inside the folders that don't match P<n>/F<n> are skipped."""
    preface = _load_dir(PREFACE_DIR, "P")
    foreword = _load_dir(FOREWORD_DIR, "F")
    return {**preface, **foreword}


def validate_manifest(manifest: dict[str, Page]) -> list[str]:
    problems: list[str] = []
    for pid in EXPECTED_IDS:
        if pid not in manifest:
            problems.append(f"missing page: {pid}")
    for pid in sorted(manifest, key=lambda p: (p[0], manifest[p].order)):
        page = manifest[pid]
        if page.is_empty:
            try:
                shown_path = page.path.relative_to(REPO_ROOT)
            except ValueError:
                shown_path = page.path
            problems.append(f"empty page: {pid} ({shown_path})")
    return problems


def corpus_hashes(manifest: dict[str, Page]) -> dict[str, str]:
    return {pid: page.sha256 for pid, page in sorted(manifest.items())}
