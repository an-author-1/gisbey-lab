"""Independent oracle for browser acceptance: reads the atlas records and the vault files
directly and does NOT import gibsey_lab, so the frontend is never checked against the
same code that produced it. (Design adopted from the independent QA pass, 2026-09-21.)"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OPERATOR_DIMENSIONS = {"ECHO": "echo", "DEVELOP": "development", "CONTRADICT": "contradiction", "BRIDGE": "bridge_relation"}
PAGES = ([f"P{i}" for i in range(1, 9)] + [f"F{i}" for i in range(1, 13)]
         + [f"LF{i}" for i in range(1, 17)] + [f"PR{i}" for i in range(1, 6)])
SUPPORT_LEVEL = 2.0  # rubric level 2 of 3
MAX_SUPPORTED, MIN_SHOWN = 5, 3


def _split(pid: str) -> tuple[str, int]:
    m = re.match(r"^([A-Z]+)(\d+)$", pid)
    return m.group(1), int(m.group(2))


def neighbors(pid: str) -> set[str]:
    prefix, n = _split(pid)
    return {f"{prefix}{n - 1}", f"{prefix}{n + 1}"} & set(PAGES)


def eligible(pid: str, policy: str) -> list[str]:
    return [d for d in PAGES if d != pid and (policy != "discovery" or d not in neighbors(pid))]


def vault_text(pid: str) -> str:
    hits = [f for f in glob.glob(str(REPO / "vault" / "*" / "*.md")) if os.path.basename(f) == pid + ".md"]
    assert len(hits) == 1, (pid, hits)
    return Path(hits[0]).read_text(encoding="utf-8")


def load_atlas() -> dict[tuple[str, str], dict]:
    config_id = json.loads((REPO / "data/atlas/active_config.json").read_text())["active"]["config_id"]
    latest: dict[tuple[str, str], dict] = {}
    with open(REPO / "data/atlas/assessments.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("mode") == "live" and r.get("config_id") == config_id and r.get("status") == "ok":
                latest[(r["source_id"], r["destination_id"])] = r
    return latest


def expected_rows(atlas: dict, pid: str, operator: str, policy: str) -> list[dict]:
    """[{destination, tier, score (0-3), confidence}] in display order."""
    dim = OPERATOR_DIMENSIONS[operator]
    rows = []
    for d in eligible(pid, policy):
        r = atlas.get((pid, d))
        if r:
            rows.append((d, r["dimensions"][dim]["score"], r["dimensions"]["direct_q_fit"]["score"], r["dimensions"][dim]["confidence"]))
    rows.sort(key=lambda x: (-x[1], -x[2], _split(x[0])))
    supported = [x for x in rows if x[1] >= SUPPORT_LEVEL - 1e-9]
    shown = [(x, "supported") for x in supported[:MAX_SUPPORTED]]
    if len(supported) < MIN_SHOWN:
        rest = [x for x in rows if x[1] < SUPPORT_LEVEL - 1e-9]
        shown += [(x, "exploratory") for x in rest[:MIN_SHOWN - len(shown)]]
    return [{"destination": x[0], "tier": tier, "score": x[1], "confidence": x[3]} for x, tier in shown]
