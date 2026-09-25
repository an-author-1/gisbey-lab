"""Binary projection (`binary-projection-v1`) of the assessment store under one manifest
(plan sections 4.1 and 4.7).

For each operator `o` with rubric dimension `dimension_of[o]` and each ordered pair of
manifest indices (i, j):

    S[o][i][j]  status code: included | assessed_below_floor | unassessed | stale |
                failed | self
    M[o][i][j]  1 iff S is `included`, else 0
    A[o][i][j]  the pair's score_norm on that dimension (float), or None where there
                is no compatible assessment (unassessed / stale / failed / self)
    assessment_ids[o][i][j]  the record the value came from, or None

`included` means: the pair is `complete` under the manifest's atlas config (latest
compatible ok record, both hashes current) AND that record's score_norm on the
operator's dimension clears SUPPORT_FLOOR (2/3, rubric level 2, the same floor the
operator buttons use). Nothing else is applied: no candidate policy, no redundancy or
confidence caution, no ranking. Discovery's adjacency exclusion is a separate mask,
`eligibility_mask`, so a supported-but-currently-ineligible edge is still an edge here.

A zero in M is not a claim that the relation is absent: read S. Unknown survives
projection as `unassessed`; a record the atlas would call stale or failed keeps that
code and contributes no value.

Several compatible ok records for one pair collapse to one edge (the atlas's own
"latest compatible" rule picks the value); the number collapsed is reported in
`counts.duplicates_collapsed` so duplicates never inflate edge counts unnoticed.

The result is deterministic for a given store + manifest (no clocks), so it can be
cached as `data/analysis/projection_<manifest_id>.json`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..atlas import api as atlas_api
from ..fields import DEFAULT_POLICY, Field
from ..memory.shortlist import clears, dimension_norm
from . import index_manifest as im

ANALYSIS_DIR = im.REPO_ROOT / "data" / "analysis"
SCHEMA = "projection/1"
STATUS_CODES = ("included", "assessed_below_floor", "unassessed", "stale", "failed", "self")


class ProjectionError(ValueError):
    pass


def projection_path(manifest_id: str, root: Path | str = ANALYSIS_DIR) -> Path:
    return Path(root) / f"projection_{manifest_id}.json"


def _grid(n: int, fill):
    return [[fill for _ in range(n)] for _ in range(n)]


def project(manifest: dict, field: Field | None = None, atlas_config: dict | None = None) -> dict:
    """Project the current store under `manifest`. The manifest must still describe the
    current vault, config and store; otherwise the projection would not be the one the
    manifest id names, so a stale manifest is refused with its reasons."""
    field = field or atlas_api.current_field()
    atlas_config = atlas_config or atlas_api.active_config(manifest.get("snapshot", {}).get("atlas_mode", "live"))
    check = im.check_manifest(manifest, field, atlas_config)
    if check["stale"]:
        raise ProjectionError(
            f"manifest {manifest['manifest_id']} is stale (current would be {check['current_manifest_id']}): "
            + "; ".join(check["reasons"] or ["manifest id differs"])
        )

    ids = im.page_ids(manifest)
    n = manifest["N"]
    ops = manifest["operator_order"]
    dimension_of = manifest["dimension_of"]
    floor = manifest["support_floor"]

    by_pair, _corrupt = atlas_api._records_by_pair(atlas_config["mode"])

    M = {op: _grid(n, 0) for op in ops}
    S = {op: _grid(n, None) for op in ops}
    A = {op: _grid(n, None) for op in ops}
    assessment_ids = {op: _grid(n, None) for op in ops}
    per_status = {op: {code: 0 for code in STATUS_CODES} for op in ops}
    duplicates_collapsed = 0
    pairs_with_duplicates = 0
    pair_status_counts = {code: 0 for code in atlas_api.STATUSES}

    for i, src in enumerate(ids):
        for j, dst in enumerate(ids):
            if i == j:
                for op in ops:
                    S[op][i][j] = "self"
                    per_status[op]["self"] += 1
                continue
            records = by_pair.get((src, dst), [])
            status, record = atlas_api._classify(records, atlas_config, field)
            pair_status_counts[status] += 1
            if status == "complete":
                compatible = sum(1 for r in records if atlas_api._classify([r], atlas_config, field)[0] == "complete")
                if compatible > 1:
                    duplicates_collapsed += compatible - 1
                    pairs_with_duplicates += 1
            for op in ops:
                if status != "complete":
                    S[op][i][j] = status  # unassessed / stale / failed, value stays unknown
                    per_status[op][status] += 1
                    continue
                norm = dimension_norm(record, dimension_of[op])
                if norm is None:  # cannot happen for a `complete` record; keep it visible if it does
                    S[op][i][j] = "failed"
                    per_status[op]["failed"] += 1
                    continue
                A[op][i][j] = norm
                assessment_ids[op][i][j] = record["assessment_id"]
                if clears(norm, floor):
                    M[op][i][j] = 1
                    S[op][i][j] = "included"
                    per_status[op]["included"] += 1
                else:
                    S[op][i][j] = "assessed_below_floor"
                    per_status[op]["assessed_below_floor"] += 1

    return {
        "schema": SCHEMA,
        "manifest_id": manifest["manifest_id"],
        "projection_rule": manifest["projection_rule"],
        "support_floor": floor,
        "collapse_rule": manifest["collapse_rule"],
        "atlas_config_id": atlas_config["config_id"],
        "atlas_mode": atlas_config["mode"],
        "policy_applied": None,
        "page_ids": ids,
        "version_ids": im.version_ids(manifest),
        "operator_order": list(ops),
        "dimension_of": dict(dimension_of),
        "M": M,
        "S": S,
        "A": A,
        "assessment_ids": assessment_ids,
        "counts": {
            "N": n,
            "off_diagonal_cells": n * (n - 1),
            "pairs": pair_status_counts,
            "per_operator": per_status,
            "included_edges": {op: per_status[op]["included"] for op in ops},
            "duplicates_collapsed": duplicates_collapsed,
            "pairs_with_duplicates": pairs_with_duplicates,
        },
        "note": (
            "M is a binary projection under the frozen support floor; 0 is not a negative verdict "
            "(read S). No candidate policy applied -- see eligibility_mask."
        ),
    }


def eligibility_mask(field: Field, policy: str = DEFAULT_POLICY, page_order: list[str] | None = None) -> list[list[int]]:
    """NxN ints in manifest order: 1 where `dst` is an eligible destination of `src`
    under `policy` (Discovery drops authored neighbors). Independent of any assessment;
    combine with M by elementwise product when a policy-restricted view is wanted."""
    ids = list(page_order) if page_order is not None else [p for p in im.AUTHORED_PAGE_ORDER if p in field.manifest]
    mask = _grid(len(ids), 0)
    for i, src in enumerate(ids):
        eligible = set(field.eligible_candidate_ids(src, policy))
        for j, dst in enumerate(ids):
            if i != j and dst in eligible:
                mask[i][j] = 1
    return mask


# --------------------------------------------------------------------------- cache


def write_projection(projection: dict, root: Path | str = ANALYSIS_DIR) -> Path:
    path = projection_path(projection["manifest_id"], root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(projection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_projection(manifest_id: str, root: Path | str = ANALYSIS_DIR) -> dict:
    path = projection_path(manifest_id, root)
    if not path.exists():
        raise ProjectionError(f"no cached projection at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("manifest_id") != manifest_id:
        raise ProjectionError(f"{path} is not a {SCHEMA} for manifest {manifest_id}")
    return data


def cached_projection(manifest: dict, root: Path | str = ANALYSIS_DIR, *, field: Field | None = None,
                      atlas_config: dict | None = None) -> tuple[dict, bool]:
    """(projection, from_cache). A cached file is keyed by manifest id, so it can only
    ever describe the store state the manifest snapshot names."""
    try:
        return load_projection(manifest["manifest_id"], root), True
    except ProjectionError:
        projection = project(manifest, field=field, atlas_config=atlas_config)
        write_projection(projection, root)
        return projection, False
