"""Context assembly: assemble(case, state, field) -> context_packet, per README's organizing function."""
from __future__ import annotations

from dataclasses import dataclass

from . import cases
from .corpus import Page
from .sentence_map import SentenceMap


class CaseError(Exception):
    pass


@dataclass(frozen=True)
class ContextPacket:
    case_id: str
    working_index: str
    source_id: str
    source_text: str
    active_id: str | None
    active_text: str | None
    criterion: str
    options: dict[str, str]       # id -> exact source text, includes "NONE"
    option_order: list[str]
    reader_state: dict


def _check_option_count(case_id: str, options: dict[str, str]) -> None:
    if len(options) > cases.MAX_OPTIONS:
        raise CaseError(
            f"{case_id}: {len(options)} options exceeds the documented TypeSafe Choice "
            f"limit of {cases.MAX_OPTIONS}; reduce candidates instead of silently truncating"
        )


def assemble_f12_micro(manifest: dict[str, Page], sentence_map: SentenceMap | None) -> ContextPacket:
    page = manifest.get(cases.MICRO_SOURCE_ID)
    if page is None or page.is_empty:
        raise CaseError(
            f"{cases.MICRO_CASE_ID} requires source page {cases.MICRO_SOURCE_ID}, which is "
            "missing or empty in the vault. Refusing to construct a case without inventing text."
        )
    if sentence_map is None or sentence_map.status != "reviewed":
        status = sentence_map.status if sentence_map else "absent"
        raise CaseError(
            f"{cases.MICRO_CASE_ID} requires a reviewed sentence mapping for "
            f"{cases.MICRO_SOURCE_ID}; current status is '{status}'. Run "
            f"'gibsey propose-sentence-map {cases.MICRO_SOURCE_ID}' then "
            f"'gibsey review-sentence-map {cases.MICRO_SOURCE_ID} --approve' after human review."
        )
    if sentence_map.source_sha256 != page.sha256:
        raise CaseError(
            f"reviewed sentence mapping for {cases.MICRO_SOURCE_ID} does not match the current "
            "source text (source was edited after review); re-propose and re-approve"
        )

    required = [cases.MICRO_ACTIVE_ID, *cases.MICRO_EXCLUDED_NEIGHBORS, *cases.MICRO_ELIGIBLE_IDS]
    missing = [sid for sid in required if sid not in sentence_map.sentences]
    if missing:
        raise CaseError(f"reviewed sentence map for {cases.MICRO_SOURCE_ID} is missing required units: {missing}")

    options = {sid: sentence_map.sentences[sid] for sid in cases.MICRO_ELIGIBLE_IDS}
    options[cases.ABSTAIN_ID] = cases.ABSTAIN_TEXT
    _check_option_count(cases.MICRO_CASE_ID, options)

    return ContextPacket(
        case_id=cases.MICRO_CASE_ID,
        working_index="AGI",
        source_id=cases.MICRO_SOURCE_ID,
        source_text=page.text,
        active_id=cases.MICRO_ACTIVE_ID,
        active_text=sentence_map.sentences[cases.MICRO_ACTIVE_ID],
        criterion=cases.MICRO_CRITERION,
        options=options,
        option_order=[*cases.MICRO_ELIGIBLE_IDS, cases.ABSTAIN_ID],
        reader_state={
            "active_page": cases.MICRO_SOURCE_ID,
            "active_passage": cases.MICRO_ACTIVE_ID,
            "excluded_neighbors": list(cases.MICRO_EXCLUDED_NEIGHBORS),
            "history": [],
        },
    )


def assemble_f12_macro(manifest: dict[str, Page]) -> ContextPacket:
    source = manifest.get(cases.MACRO_SOURCE_ID)
    if source is None or source.is_empty:
        raise CaseError(
            f"{cases.MACRO_CASE_ID} requires source page {cases.MACRO_SOURCE_ID}, which is "
            "missing or empty in the vault. Refusing to construct a case without inventing text."
        )

    candidate_ids = [pid for pid in manifest if pid != cases.MACRO_SOURCE_ID]
    empty_candidates = sorted(pid for pid in candidate_ids if manifest[pid].is_empty)
    if empty_candidates:
        raise CaseError(
            f"{cases.MACRO_CASE_ID} requires all nineteen candidate pages to have content; "
            f"empty: {empty_candidates}"
        )

    order = sorted(candidate_ids, key=lambda pid: (pid[0], manifest[pid].order))
    options = {pid: manifest[pid].text for pid in order}
    options[cases.ABSTAIN_ID] = cases.ABSTAIN_TEXT
    _check_option_count(cases.MACRO_CASE_ID, options)

    return ContextPacket(
        case_id=cases.MACRO_CASE_ID,
        working_index="AGI",
        source_id=cases.MACRO_SOURCE_ID,
        source_text=source.text,
        active_id=None,
        active_text=None,
        criterion=cases.MACRO_CRITERION,
        options=options,
        option_order=[*order, cases.ABSTAIN_ID],
        reader_state={"active_page": cases.MACRO_SOURCE_ID, "active_passage": None, "history": []},
    )


def assemble(case_id: str, manifest: dict[str, Page], sentence_map: SentenceMap | None = None) -> ContextPacket:
    if case_id == cases.MICRO_CASE_ID:
        return assemble_f12_micro(manifest, sentence_map)
    if case_id == cases.MACRO_CASE_ID:
        return assemble_f12_macro(manifest)
    raise CaseError(f"unknown case: {case_id!r}; known cases: {cases.KNOWN_CASE_IDS}")
