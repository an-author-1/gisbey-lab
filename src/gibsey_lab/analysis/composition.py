"""Ordered two-step operator composition (plan section 4.8), pure Python.

With the source-row convention, `(M_first M_second)[i][j] = sum_k M_first[i][k] *
M_second[k][j]` counts two-edge relation walks i -> k -> j taking `ops[0]` first and
`ops[1]` second. Order matters: E@D != D@E in general.

What a result is and is not (plan section 4.9): a relation walk in a frozen projection.
Counts are exact integers over distinct version sequences; witnesses name the exact
intermediate and the assessment ids behind each edge. A count is NOT a score-valid
simulation (no reader state, guard, or eligibility policy is consulted) and NOT a
recorded reader performance. Zero means no included walk in this snapshot; unknown
edges (see the projection's S) can still hide possibilities.

Witness display is capped (default 100) with deterministic ordering by manifest index
(i, k, j); the exact total is always kept and `truncated` says when the list is short.
"""
from __future__ import annotations

import hashlib
import json

from . import index_manifest as im

KIND = "relation_walk"
LABEL = "relation walks in a frozen projection — not score-valid navigation, not corpus truth"
DEFAULT_CAP = 100


class CompositionError(ValueError):
    pass


def _digest(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def route_id(manifest: dict, ops: tuple[str, str], steps: list[tuple[str | None, str | None, str]], v0: str) -> str:
    """hash(manifest_id, projection_rule, op sequence, [(v0), (op1, aid1, v1), (op2, aid2, v2)])."""
    return "route_" + _digest({
        "schema": "relation-walk/1",
        "manifest_id": manifest["manifest_id"],
        "projection_rule": manifest["projection_rule"],
        "ops": list(ops),
        "path": [[v0]] + [[op, aid, v] for op, aid, v in steps],
    })[:20]


def matmul(M_first: list[list[int]], M_second: list[list[int]]) -> list[list[int]]:
    """Exact integer product of two NxN 0/1 matrices."""
    n = len(M_first)
    if any(len(row) != n for row in M_first) or len(M_second) != n or any(len(row) != n for row in M_second):
        raise CompositionError("both matrices must be square and the same size")
    out = [[0] * n for _ in range(n)]
    for i in range(n):
        row = M_first[i]
        acc = out[i]
        for k in range(n):
            if row[k]:
                second = M_second[k]
                for j in range(n):
                    if second[j]:
                        acc[j] += 1
    return out


def _source_index(manifest: dict, source) -> int | None:
    if source is None:
        return None
    if isinstance(source, int) and not isinstance(source, bool):
        if not 0 <= source < manifest["N"]:
            raise CompositionError(f"source index {source} out of bounds [0, {manifest['N']})")
        return source
    try:
        return im.index_of(manifest, str(source))
    except im.ManifestError as e:
        raise CompositionError(str(e)) from None


def compose(M_first: list[list[int]], M_second: list[list[int]], manifest: dict, source=None, *,
            ops: tuple[str, str] = ("FIRST", "SECOND"), assessment_ids: tuple[list, list] | None = None,
            cap: int = DEFAULT_CAP) -> dict:
    """Two-step composition `M_first` then `M_second` in manifest coordinates.

    `source` (page id or manifest index) restricts witnesses and totals to that row;
    the full count matrix is always returned. `assessment_ids` are the projection's
    per-operator id grids for the two operators, so each witness step cites its record
    (None when composing bare matrices, e.g. a fixture)."""
    n = manifest["N"]
    if len(M_first) != n:
        raise CompositionError(f"matrix size {len(M_first)} does not match manifest N={n}")
    counts = matmul(M_first, M_second)
    src_index = _source_index(manifest, source)
    ids, versions = im.page_ids(manifest), im.version_ids(manifest)
    ids_first = assessment_ids[0] if assessment_ids else None
    ids_second = assessment_ids[1] if assessment_ids else None
    cap = max(0, int(cap))

    rows = [src_index] if src_index is not None else range(n)
    total = sum(counts[i][j] for i in rows for j in range(n))
    witnesses: list[dict] = []
    shown = 0
    for i in rows:  # (i, k, j) ascending by manifest index -- deterministic
        for k in range(n):
            if not M_first[i][k]:
                continue
            for j in range(n):
                if not M_second[k][j]:
                    continue
                if shown >= cap:
                    break
                aid1 = ids_first[i][k] if ids_first else None
                aid2 = ids_second[k][j] if ids_second else None
                steps = [(ops[0], aid1, versions[k]), (ops[1], aid2, versions[j])]
                witnesses.append({
                    "i": i, "k": k, "j": j,
                    "pages": [ids[i], ids[k], ids[j]],
                    "versions": [versions[i], versions[k], versions[j]],
                    "steps": [
                        {"operator": ops[0], "from": versions[i], "to": versions[k], "assessment_id": aid1},
                        {"operator": ops[1], "from": versions[k], "to": versions[j], "assessment_id": aid2},
                    ],
                    "route_id": route_id(manifest, ops, steps, versions[i]),
                })
                shown += 1

    destinations = None
    if src_index is not None:
        destinations = [
            {"index": j, "page_id": ids[j], "version_id": versions[j], "count": counts[src_index][j]}
            for j in range(n) if counts[src_index][j] > 0
        ]
    return {
        "kind": KIND,
        "label": LABEL,
        "manifest_id": manifest["manifest_id"],
        "projection_rule": manifest["projection_rule"],
        "ops": list(ops),
        "source": None if src_index is None else {"index": src_index, "page_id": ids[src_index],
                                                    "version_id": versions[src_index]},
        "N": n,
        "counts": counts,
        "total": total,
        "reachable": None if destinations is None else [d["page_id"] for d in destinations],
        "destinations": destinations,
        # scoped like `total`: the source row's destinations reached, or the whole matrix
        "cells_nonzero": sum(1 for i in rows for j in range(n) if counts[i][j] > 0),
        "cells_scope": f"from {ids[src_index]}" if src_index is not None else "whole matrix",
        "witnesses": witnesses,
        "witness_cap": cap,
        "witnesses_shown": len(witnesses),
        "truncated": len(witnesses) < total,
    }


def witnesses_for(M_first: list[list[int]], M_second: list[list[int]], i: int, j: int) -> list[tuple[int, int, int]]:
    """Every (i, k, j) walk for one cell, ascending in k. Uncapped; exact."""
    return [(i, k, j) for k in range(len(M_first)) if M_first[i][k] and M_second[k][j]]


def compare_orders(manifest: dict, projection: dict, op_a: str, op_b: str, source=None, *,
                   cap: int = DEFAULT_CAP) -> dict:
    """Both products A@B and B@A from one projection, and where they differ. With a
    `source`, per-destination counts are that row's; without one, each destination's
    count is summed over all sources and `cells_differing` counts the whole matrix."""
    for op in (op_a, op_b):
        if op not in projection["M"]:
            raise CompositionError(f"projection has no operator {op!r}; has {list(projection['M'])}")
    M_a, M_b = projection["M"][op_a], projection["M"][op_b]
    ids_a, ids_b = projection["assessment_ids"][op_a], projection["assessment_ids"][op_b]
    ab = compose(M_a, M_b, manifest, source, ops=(op_a, op_b), assessment_ids=(ids_a, ids_b), cap=cap)
    ba = compose(M_b, M_a, manifest, source, ops=(op_b, op_a), assessment_ids=(ids_b, ids_a), cap=cap)
    n = manifest["N"]
    ids = im.page_ids(manifest)
    src_index = _source_index(manifest, source)

    def column(counts, j):
        return counts[src_index][j] if src_index is not None else sum(counts[i][j] for i in range(n))

    per_destination = []
    for j in range(n):
        c_ab, c_ba = column(ab["counts"], j), column(ba["counts"], j)
        if c_ab or c_ba:
            per_destination.append({"index": j, "page_id": ids[j], f"{op_a}>{op_b}": c_ab, f"{op_b}>{op_a}": c_ba,
                                    "difference": c_ab - c_ba})
    cells_differing = sum(1 for i in range(n) for j in range(n) if ab["counts"][i][j] != ba["counts"][i][j])
    return {
        "kind": KIND,
        "label": LABEL,
        "manifest_id": manifest["manifest_id"],
        "projection_rule": manifest["projection_rule"],
        "source": ab["source"],
        "orders": {f"{op_a}>{op_b}": ab, f"{op_b}>{op_a}": ba},
        "totals": {f"{op_a}>{op_b}": ab["total"], f"{op_b}>{op_a}": ba["total"]},
        "per_destination": per_destination,
        "only_under": {
            f"{op_a}>{op_b}": [d["page_id"] for d in per_destination if d[f"{op_a}>{op_b}"] and not d[f"{op_b}>{op_a}"]],
            f"{op_b}>{op_a}": [d["page_id"] for d in per_destination if d[f"{op_b}>{op_a}"] and not d[f"{op_a}>{op_b}"]],
        },
        "cells_differing": cells_differing,
        "orders_equal": cells_differing == 0,
    }
