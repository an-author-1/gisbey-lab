"""The two candidate fields the reader app can operate over.

`holdout-21`: the London Fox / Princhetta holdout corpus only (21 pages). This is the
field the existing full-field and tournament experiments were run against.

`full-41`: the complete vault (20 training pages + 21 holdout pages = 41). This
combination has never been exercised by a live experiment -- it is a genuinely new,
explicitly labeled condition, not an extension of prior recorded results.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import cases
from .corpus import Page, load_manifest
from .holdout_corpus import load_holdout_manifest

HOLDOUT_21 = "holdout-21"
FULL_41 = "full-41"
KNOWN_FIELDS = (HOLDOUT_21, FULL_41)
DEFAULT_FIELD = HOLDOUT_21

# Page IDs mix two naming schemes: single-letter (P1, F12) and two-letter (LF16, PR5)
# prefixes. holdout_corpus.canonical_order's fixed pid[:2] slicing only handles the
# latter; this splits on the letters/digits boundary generically, so it works for both
# in the combined 41-page field.
_ID_SPLIT = re.compile(r"^([A-Za-z]+)(\d+)$")


def _sort_key(pid: str) -> tuple[str, int]:
    match = _ID_SPLIT.match(pid)
    if not match:
        return (pid, 0)
    prefix, number = match.groups()
    return (prefix, int(number))


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
        return Field(id=FULL_41, label="Complete 41-page corpus (training + holdout)", manifest=manifest)
    raise FieldError(f"unknown field: {field_id!r}; known fields: {KNOWN_FIELDS}")


def validate_source_and_candidates(field: Field, source_id: str) -> None:
    if source_id not in field.manifest:
        raise FieldError(f"source {source_id!r} is not eligible in field {field.id!r}")
    source = field.manifest[source_id]
    if source.is_empty:
        raise FieldError(f"source {source_id!r} is empty in field {field.id!r}")
    candidates = field.candidate_ids_for(source_id)
    empty_candidates = [pid for pid in candidates if field.manifest[pid].is_empty]
    if empty_candidates:
        raise FieldError(f"field {field.id!r} has empty candidate pages: {empty_candidates}")
    option_count = len(candidates) + 1  # + NONE
    if option_count > cases.MAX_OPTIONS:
        raise FieldError(
            f"field {field.id!r} would offer {option_count} options for source {source_id!r}, "
            f"exceeding the documented TypeSafe Choice limit of {cases.MAX_OPTIONS}"
        )
