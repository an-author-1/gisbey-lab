"""Loader for the holdout corpus: London Fox Who Vertically Disintegrates (LF1-16) and
Princhetta Who Thinks Herself Alive (PR1-5). Kept fully separate from corpus.py's
training-corpus loader -- no shared code path, so the two corpora cannot mix."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .corpus import REPO_ROOT, VAULT_DIR, Page

LF_DIR = VAULT_DIR / "London Fox Who Vertically Disintegrates"
PR_DIR = VAULT_DIR / "Princhetta Who Thinks Herself Alive"

ID_PATTERN = re.compile(r"^(LF|PR)\s*(\d{1,2})$")

EXPECTED_LF_IDS = [f"LF{i}" for i in range(1, 17)]
EXPECTED_PR_IDS = [f"PR{i}" for i in range(1, 6)]
EXPECTED_HOLDOUT_IDS = EXPECTED_LF_IDS + EXPECTED_PR_IDS  # 21 pages


class HoldoutCorpusError(Exception):
    pass


def _load_dir(dir_path: Path, expected_prefix: str) -> dict[str, Page]:
    if not dir_path.is_dir():
        raise HoldoutCorpusError(f"expected holdout folder not found: {dir_path}")
    pages: dict[str, Page] = {}
    for f in sorted(dir_path.glob("*.md")):
        match = ID_PATTERN.match(f.stem)
        if not match or match.group(1) != expected_prefix:
            continue
        page_id = f"{match.group(1)}{match.group(2)}"
        if page_id in pages:
            raise HoldoutCorpusError(f"duplicate holdout page id: {page_id} ({f})")
        text = f.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        pages[page_id] = Page(id=page_id, path=f, text=text, sha256=digest, order=int(match.group(2)))
    return pages


def load_holdout_manifest() -> dict[str, Page]:
    lf = _load_dir(LF_DIR, "LF")
    pr = _load_dir(PR_DIR, "PR")
    manifest = {**lf, **pr}
    missing = [pid for pid in EXPECTED_HOLDOUT_IDS if pid not in manifest]
    if missing:
        raise HoldoutCorpusError(f"missing expected holdout pages: {missing}")
    return manifest


def canonical_order(ids) -> list[str]:
    return sorted(ids, key=lambda pid: (pid[:2], int(pid[2:])))
