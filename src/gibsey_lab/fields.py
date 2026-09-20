"""The two candidate fields the reader app can operate over.

`holdout-21`: the London Fox / Princhetta holdout corpus only (21 pages). This is the
field the existing full-field and tournament experiments were run against. Kept
available as an optional experiment setting; historical sessions and results recorded
against it are unchanged.

`full-41`: the complete vault (20 training pages + 21 holdout pages = 41), the default
for new reading sessions. Every page is eligible as a source, and for any source, every
other page in the field is an eligible destination for all four operators (40 candidates
+ NONE).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import cases
from .corpus import EXPECTED_IDS as TRAINING_EXPECTED_IDS
from .corpus import Page, load_manifest
from .holdout_corpus import EXPECTED_HOLDOUT_IDS, load_holdout_manifest

HOLDOUT_21 = "holdout-21"
FULL_41 = "full-41"
KNOWN_FIELDS = (FULL_41, HOLDOUT_21)
DEFAULT_FIELD = FULL_41

# Candidate eligibility policy: which pages may serve as a destination for a source.
# "discovery" (default) excludes the source's immediate authored predecessor/successor
# within its own text, so an operator isn't just picking the next/previous page.
# "include-adjacent" is the original unrestricted behavior (every other page eligible).
DISCOVERY = "discovery"
INCLUDE_ADJACENT = "include-adjacent"
KNOWN_POLICIES = (DISCOVERY, INCLUDE_ADJACENT)
DEFAULT_POLICY = DISCOVERY

EXPECTED_FULL_41_IDS = TRAINING_EXPECTED_IDS + EXPECTED_HOLDOUT_IDS

# Human-readable groupings for the page picker: (prefix, title). Order here is the
# display order of groups; pages within a group are ordered numerically.
TEXT_GROUPS: list[tuple[str, str]] = [
    ("P", "an author's preface"),
    ("F", "The Foreword to the Foreword to an author's preface"),
    ("LF", "London Fox Who Vertically Disintegrates"),
    ("PR", "Princhetta Who Thinks Herself Alive"),
]

# Page IDs mix two naming schemes: single-letter (P1, F12) and two-letter (LF16, PR5)
# prefixes. A fixed pid[:2] slice breaks on the single-letter ids (int('') on the
# leftover ""), so this splits on the letters/digits boundary generically instead.
_ID_SPLIT = re.compile(r"^([A-Za-z]+)(\d+)$")


def _sort_key(pid: str) -> tuple[str, int]:
    match = _ID_SPLIT.match(pid)
    if not match:
        return (pid, 0)
    prefix, number = match.groups()
    return (prefix, int(number))


def prefix_of(pid: str) -> str:
    match = _ID_SPLIT.match(pid)
    return match.group(1) if match else pid


class FieldError(Exception):
    pass


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    manifest: dict[str, Page]

    def all_ids(self) -> list[str]:
        return sorted(self.manifest, key=_sort_key)

    def candidate_ids_for(self, source_id: str) -> list[str]:
        return sorted((pid for pid in self.manifest if pid != source_id), key=_sort_key)

    def neighbors_of(self, source_id: str) -> dict[str, str | None]:
        """The source's immediate authored predecessor/successor within its own text,
        derived from the manifest's explicit numeric Page.order -- never crossing into a
        different prefix (P/F/LF/PR boundaries are never treated as adjacency)."""
        source = self.manifest[source_id]
        prefix = prefix_of(source_id)
        by_order = {p.order: pid for pid, p in self.manifest.items() if prefix_of(pid) == prefix}
        return {
            "previous": by_order.get(source.order - 1),
            "next": by_order.get(source.order + 1),
        }

    def eligible_candidate_ids(self, source_id: str, policy: str = DEFAULT_POLICY) -> list[str]:
        candidates = self.candidate_ids_for(source_id)
        if policy == DISCOVERY:
            excluded = {n for n in self.neighbors_of(source_id).values() if n is not None}
            candidates = [pid for pid in candidates if pid not in excluded]
        elif policy != INCLUDE_ADJACENT:
            raise FieldError(f"unknown candidate policy: {policy!r}; known policies: {KNOWN_POLICIES}")
        return candidates

    def grouped_ids(self) -> list[dict]:
        """Page picker grouping: by authored text, pages ordered numerically within
        each group. Only groups actually present in this field are included."""
        groups = []
        for prefix, title in TEXT_GROUPS:
            pages = sorted((pid for pid in self.manifest if prefix_of(pid) == prefix), key=_sort_key)
            if pages:
                groups.append({"prefix": prefix, "title": title, "pages": pages})
        return groups


def load_field(field_id: str) -> Field:
    if field_id == HOLDOUT_21:
        manifest = load_holdout_manifest()
        return Field(id=HOLDOUT_21, label="21-page holdout field (London Fox / Princhetta)", manifest=manifest)
    if field_id == FULL_41:
        training = load_manifest()
        holdout = load_holdout_manifest()
        overlap = set(training) & set(holdout)
        if overlap:
            raise FieldError(f"unexpected ID overlap between corpora: {sorted(overlap)}")
        manifest = {**training, **holdout}
        missing = [pid for pid in EXPECTED_FULL_41_IDS if pid not in manifest]
        if missing:
            raise FieldError(f"field {FULL_41!r} is missing expected pages: {missing}")
        if len(manifest) != len(EXPECTED_FULL_41_IDS):
            extra = sorted(set(manifest) - set(EXPECTED_FULL_41_IDS))
            raise FieldError(f"field {FULL_41!r} has unexpected extra pages: {extra}")
        return Field(id=FULL_41, label="Complete 41-page corpus (training + holdout)", manifest=manifest)
    raise FieldError(f"unknown field: {field_id!r}; known fields: {KNOWN_FIELDS}")


def check_full_field_completeness() -> list[str]:
    """Report-only check (never silently excludes pages): returns a list of problem
    strings -- missing IDs, duplicate IDs across the two corpora -- or an empty list if
    the manifest is exactly the expected 41 pages. Safe to call even if load_field(41)
    would raise (it re-derives the two manifests independently)."""
    problems: list[str] = []
    try:
        training = load_manifest()
    except Exception as e:  # noqa: BLE001
        problems.append(f"training corpus failed to load: {e}")
        training = {}
    try:
        holdout = load_holdout_manifest()
    except Exception as e:  # noqa: BLE001
        problems.append(f"holdout corpus failed to load: {e}")
        holdout = {}

    overlap = sorted(set(training) & set(holdout))
    if overlap:
        problems.append(f"duplicate IDs present in both corpora: {overlap}")

    combined = {**training, **holdout}
    missing = [pid for pid in EXPECTED_FULL_41_IDS if pid not in combined]
    if missing:
        problems.append(f"missing pages: {missing}")

    for pid, page in combined.items():
        if page.is_empty:
            problems.append(f"empty page: {pid}")

    return problems


def validate_source_and_candidates(field: Field, source_id: str, policy: str = DEFAULT_POLICY) -> None:
    if source_id not in field.manifest:
        raise FieldError(f"source {source_id!r} is not eligible in field {field.id!r}")
    source = field.manifest[source_id]
    if source.is_empty:
        raise FieldError(f"source {source_id!r} is empty in field {field.id!r}")
    candidates = field.eligible_candidate_ids(source_id, policy)
    empty_candidates = [pid for pid in candidates if field.manifest[pid].is_empty]
    if empty_candidates:
        raise FieldError(f"field {field.id!r} has empty candidate pages: {empty_candidates}")
    option_count = len(candidates) + 1  # + NONE
    if option_count > cases.MAX_OPTIONS:
        raise FieldError(
            f"field {field.id!r} would offer {option_count} options for source {source_id!r}, "
            f"exceeding the documented TypeSafe Choice limit of {cases.MAX_OPTIONS}"
        )
