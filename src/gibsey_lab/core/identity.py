"""Immutable references (v0.3 plan §3, §4.7).

A logical page ID ("P1") names an authored slot; a content-version ID names exact bytes.
The two are never interchangeable: encounters, bonds and offers cite versions.

    version_id("P1", sha256) == "P1@c8adbba7f4ed"      (page ID + first 12 hex of the text sha256)

A bond version cites both endpoint versions, the operator, and the exact offered wording;
its ID is a content hash, so identical wording between identical versions is one bond
version wherever it appears, and any change of wording or endpoint is a new bond version.
"""
from __future__ import annotations

import hashlib
import json
import re

VERSION_ID_RE = re.compile(r"^(?P<page>[A-Z]+[0-9]+)@(?P<sha12>[0-9a-f]{12})$")
OPERATORS = ("ECHO", "DEVELOP", "CONTRADICT", "BRIDGE")


def version_id(page_id: str, sha256: str) -> str:
    if not re.match(r"^[A-Z]+[0-9]+$", page_id or ""):
        raise ValueError(f"not a page id: {page_id!r}")
    if not re.match(r"^[0-9a-f]{64}$", sha256 or ""):
        raise ValueError(f"not a sha256: {sha256!r}")
    return f"{page_id}@{sha256[:12]}"


def parse_version_id(vid: str) -> tuple[str, str]:
    """-> (page_id, sha12)."""
    m = VERSION_ID_RE.match(vid or "")
    if not m:
        raise ValueError(f"not a content-version id: {vid!r}")
    return m.group("page"), m.group("sha12")


def page_of(vid: str) -> str:
    return parse_version_id(vid)[0]


def _digest(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def bond_version_id(*, source_version: str, destination_version: str, operator: str, wording: str) -> str:
    """Content hash of exactly what a bond offers. `wording` is the exact offered sentence."""
    if operator not in OPERATORS:
        raise ValueError(f"unknown operator: {operator!r}")
    parse_version_id(source_version)
    parse_version_id(destination_version)
    if not isinstance(wording, str) or not wording.strip():
        raise ValueError("a bond version needs its exact offered wording")
    return "bond_" + _digest({
        "schema": "bond-version/1", "source_version": source_version, "destination_version": destination_version,
        "operator": operator, "wording": wording,
    })[:20]


def offer_set_id(*, session_id: str, revision: int, source_version: str, operator: str, policy: str,
                 bond_version_ids: list[str], options_policy_version: str) -> str:
    """Deterministic: the same bonds in the same order at the same session revision give
    the same id, so a retried resolve returns the same persisted offer set."""
    return "offers_" + _digest({
        "schema": "offer-set/1", "session_id": session_id, "revision": revision, "source_version": source_version,
        "operator": operator, "policy": policy, "bonds": list(bond_version_ids),
        "options_policy_version": options_policy_version,
    })[:20]


def request_fingerprint(payload: dict) -> str:
    """What makes two requests 'the same request': every input that affects the action."""
    return _digest({"schema": "action-request/1", **payload})
