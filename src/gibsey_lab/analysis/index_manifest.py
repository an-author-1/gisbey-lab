"""Index manifest (`index-manifest/1`): the coordinate system every matrix, export, route
witness and inspector view shares (plan section 4.7).

Guarantees:
- Page order is the AUTHORED order, written out as an explicit list below
  (P1..P8, F1..F12, LF1..LF16, PR1..PR5). It is never `Field.all_ids()` (which sorts
  prefixes alphabetically: F, LF, P, PR), never filesystem order, never retrieval order.
- Every row cites a content-version id (`P1@<sha12>`, see `core.identity`); a changed page
  text is a different version, hence a different manifest.
- The snapshot records which atlas the manifest was taken against: config id, rubric,
  pinned model, the set of `complete` assessment ids (as a hash), the store size and the
  ordered corpus hash. `manifest_id` hashes page order + operator order + snapshot, so
  any of those changing yields a new id. Existing journeys keep their old manifest.
- `offset(i, j, o) = ((i * N) + j) * O + o` is an element offset for an optional flat
  export, with `decode` as its exact inverse; both validate bounds.
- A manifest loaded from disk is checked against the current vault and config and reports
  its `stale` reasons; nothing here rebuilds one silently.

Private imports from `atlas.api` (`_records_by_pair`, `_classify`): the atlas keeps
"latest compatible ok record per pair" as a computed view with no public wrapper yet.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..atlas import api as atlas_api
from ..atlas import store as atlas_store
from ..core.identity import OPERATORS, version_id
from ..fields import Field
from ..memory.operator_options import OPERATOR_DIMENSIONS, SUPPORT_FLOOR

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "data" / "atlas" / "index_manifest.json"

SCHEMA = "index-manifest/1"
PROJECTION_RULE = "binary-projection-v1"
COLLAPSE_RULE = "latest compatible ok record per pair"
OPERATOR_ORDER: tuple[str, ...] = OPERATORS  # ("ECHO", "DEVELOP", "CONTRADICT", "BRIDGE")

# The authored order of the 41-page vault. Explicit on purpose: this list, not any
# sort, defines row/column indices. Extending the vault means appending here (a new
# manifest), never re-sorting.
AUTHORED_PAGE_ORDER: tuple[str, ...] = (
    *(f"P{i}" for i in range(1, 9)),
    *(f"F{i}" for i in range(1, 13)),
    *(f"LF{i}" for i in range(1, 17)),
    *(f"PR{i}" for i in range(1, 6)),
)


class ManifestError(ValueError):
    pass


def _digest(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- build


def complete_records(field: Field, atlas_config: dict) -> dict[tuple[str, str], dict]:
    """(source_id, destination_id) -> the latest compatible ok record, for every pair
    that is `complete` under `atlas_config`. Pairs with no compatible record are absent."""
    by_pair, _ = atlas_api._records_by_pair(atlas_config["mode"])
    out: dict[tuple[str, str], dict] = {}
    for pair, records in by_pair.items():
        src, dst = pair
        if src not in field.manifest or dst not in field.manifest:
            continue  # a record about a page outside this field cannot be placed
        status, record = atlas_api._classify(records, atlas_config, field)
        if status == "complete" and record is not None:
            out[pair] = record
    return out


def _snapshot(field: Field, atlas_config: dict, page_order: list[dict]) -> dict:
    records, _corrupt = atlas_store.read_assessments()
    complete = complete_records(field, atlas_config)
    assessment_ids = sorted(r["assessment_id"] for r in complete.values())
    return {
        "atlas_config_id": atlas_config["config_id"],
        "atlas_mode": atlas_config["mode"],
        "rubric_version": atlas_config["rubric_version"],
        "pinned_returned_model": atlas_config.get("pinned_returned_model"),
        "assessment_set_sha256": _digest(assessment_ids),
        "complete_pairs": len(assessment_ids),
        "records_in_store": len(records),
        "corpus_sha256": _digest([row["version_id"] for row in page_order]),
    }


def build_manifest(field: Field, atlas_config: dict) -> dict:
    """The manifest for `field` under `atlas_config` right now. The field must hold
    exactly the authored 41 pages; any other set is refused rather than reordered."""
    missing = [pid for pid in AUTHORED_PAGE_ORDER if pid not in field.manifest]
    extra = sorted(set(field.manifest) - set(AUTHORED_PAGE_ORDER))
    if missing or extra:
        raise ManifestError(
            f"field {field.id!r} does not match the authored page list: missing {missing}, extra {extra}"
        )
    page_order = [
        {"index": i, "page_id": pid, "version_id": version_id(pid, field.manifest[pid].sha256),
         "sha256": field.manifest[pid].sha256}
        for i, pid in enumerate(AUTHORED_PAGE_ORDER)
    ]
    operator_order = list(OPERATOR_ORDER)
    snapshot = _snapshot(field, atlas_config, page_order)
    manifest_id = "man-" + _digest(
        {"page_order": page_order, "operator_order": operator_order, "snapshot": snapshot}
    )[:20]
    return {
        "schema": SCHEMA,
        "manifest_id": manifest_id,
        "field": field.id,
        "page_order": page_order,
        "operator_order": operator_order,
        "dimension_of": {op: OPERATOR_DIMENSIONS[op] for op in operator_order},
        "snapshot": snapshot,
        "projection_rule": PROJECTION_RULE,
        "support_floor": SUPPORT_FLOOR,
        "collapse_rule": COLLAPSE_RULE,
        "N": len(page_order),
        "O": len(operator_order),
        "note": "authored page order (explicit list), never Field.all_ids() or filesystem order",
    }


# --------------------------------------------------------------------------- coordinates


def page_ids(manifest: dict) -> list[str]:
    return [row["page_id"] for row in manifest["page_order"]]


def version_ids(manifest: dict) -> list[str]:
    return [row["version_id"] for row in manifest["page_order"]]


def index_of(manifest: dict, page_id: str) -> int:
    for row in manifest["page_order"]:
        if row["page_id"] == page_id:
            return row["index"]
    raise ManifestError(f"{page_id!r} is not a page of manifest {manifest['manifest_id']}")


def operator_index(manifest: dict, operator: str) -> int:
    ops = manifest["operator_order"]
    if operator not in ops:
        raise ManifestError(f"unknown operator {operator!r}; manifest operators: {ops}")
    return ops.index(operator)


def _check_bounds(manifest: dict, i: int, j: int, o: int) -> None:
    n, big_o = manifest["N"], manifest["O"]
    for name, value, limit in (("i", i, n), ("j", j, n), ("o", o, big_o)):
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < limit:
            raise ManifestError(f"coordinate {name}={value!r} out of bounds [0, {limit})")


def offset(manifest: dict, i: int, j: int, o: int) -> int:
    """Element offset with operator as the fastest-changing axis: ((i*N)+j)*O+o."""
    _check_bounds(manifest, i, j, o)
    return ((i * manifest["N"]) + j) * manifest["O"] + o


def decode(manifest: dict, off: int) -> tuple[int, int, int]:
    """Inverse of `offset`: -> (i, j, o)."""
    n, big_o = manifest["N"], manifest["O"]
    if not isinstance(off, int) or isinstance(off, bool) or not 0 <= off < n * n * big_o:
        raise ManifestError(f"offset {off!r} out of bounds [0, {n * n * big_o})")
    o = off % big_o
    ij = off // big_o
    return ij // n, ij % n, o


# --------------------------------------------------------------------------- persistence


def write_manifest(manifest: dict, path: Path | str = MANIFEST_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_manifest(path: Path | str = MANIFEST_PATH) -> dict:
    """The manifest exactly as written. Pair with `check_manifest` before trusting it."""
    path = Path(path)
    if not path.exists():
        raise ManifestError(f"no index manifest at {path}; run `gibsey analysis-manifest`")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ManifestError(f"{path} is not an {SCHEMA} file")
    return data


def check_manifest(manifest: dict, field: Field, atlas_config: dict) -> dict:
    """Compare a (loaded) manifest with the manifest the current vault and config would
    produce. Reports every difference as a reason; never rebuilds or rewrites anything."""
    current = build_manifest(field, atlas_config)
    reasons: list[str] = []
    old_rows, new_rows = manifest.get("page_order", []), current["page_order"]
    if [r["page_id"] for r in old_rows] != [r["page_id"] for r in new_rows]:
        reasons.append("page order differs from the authored list")
    else:
        for old, new in zip(old_rows, new_rows):
            if old["version_id"] != new["version_id"]:
                reasons.append(f"{old['page_id']} text changed: {old['version_id']} -> {new['version_id']}")
    if manifest.get("operator_order") != current["operator_order"]:
        reasons.append("operator order differs")
    old_snap, new_snap = manifest.get("snapshot", {}), current["snapshot"]
    labels = {
        "atlas_config_id": "atlas config", "atlas_mode": "atlas mode", "rubric_version": "rubric",
        "pinned_returned_model": "pinned returned model",
        "assessment_set_sha256": "set of complete assessments", "complete_pairs": "complete pair count",
        "records_in_store": "records in store",
    }
    for key, label in labels.items():
        if old_snap.get(key) != new_snap.get(key):
            reasons.append(f"{label} changed: {old_snap.get(key)!r} -> {new_snap.get(key)!r}")
    if manifest.get("projection_rule") != current["projection_rule"]:
        reasons.append(f"projection rule changed: {manifest.get('projection_rule')!r} -> {current['projection_rule']!r}")
    return {
        "manifest_id": manifest.get("manifest_id"),
        "current_manifest_id": current["manifest_id"],
        "stale": manifest.get("manifest_id") != current["manifest_id"] or bool(reasons),
        "reasons": reasons,
    }
