"""Append-only record of every reader request outcome.

One JSONL line per operator request ("Ask Jev") and per offer request ("Show possible
next pages") -- selections, abstentions, empty candidate lists, provider errors and
server-side exceptions alike. A rerun appends a new line; nothing here ever rewrites or
deletes an earlier one, so earlier results stay recoverable.

Outcome states (exact ids, shared with the browser):

- `not_requested`  nothing has been asked for this page/operator (client-side only)
- `loading`        a request is in flight (client-side only)
- `selected`       Jev was asked and chose a destination
- `abstained`      Jev WAS asked, had `candidate_count` real candidates, and chose NONE
- `no_candidates`  eligibility produced an empty candidate list, so Jev was NEVER asked
- `error`          the request failed (provider error, validation error, server exception)
- `offers` / `no_qualified` / `atlas_incomplete`  offer hands only

`abstained` and `no_candidates` are different facts and are never merged.

Runs recorded before this file existed are not copied into it: `backfill_from_runs`
returns them as a computed, read-only view (`source: "recorded"`).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..corpus import REPO_ROOT

DEFAULT_OUTCOMES_PATH = REPO_ROOT / "data" / "reader_outcomes.jsonl"
OUTCOMES_PATH = DEFAULT_OUTCOMES_PATH

SCHEMA = "reader-outcome/1"

NOT_REQUESTED = "not_requested"
LOADING = "loading"
SELECTED = "selected"
ABSTAINED = "abstained"
NO_CANDIDATES = "no_candidates"
ERROR = "error"
OFFERS = "offers"
NO_QUALIFIED = "no_qualified"
ATLAS_INCOMPLETE = "atlas_incomplete"

OPERATOR_STATES = (NOT_REQUESTED, LOADING, SELECTED, ABSTAINED, NO_CANDIDATES, ERROR)
OFFER_STATES = (NOT_REQUESTED, LOADING, OFFERS, NO_QUALIFIED, NO_CANDIDATES, ATLAS_INCOMPLETE, ERROR)
# History refinement of a ranked operator option list (kind "options_refinement").
REFINED = "refined"                  # every displayed option got a valid history-conditioned answer
REFINE_PARTIAL = "refine_partial"    # some did not: the base order is kept
REFINE_FAILED = "refine_failed"      # none did (provider failure, budget refusal, ...): the base order is kept
REFINE_STATES = (REFINED, REFINE_PARTIAL, REFINE_FAILED, ERROR)

PERSISTED_OFFER_STATES = (OFFERS, NO_QUALIFIED, NO_CANDIDATES, ATLAS_INCOMPLETE, ERROR)
PERSISTED_STATES = (SELECTED, ABSTAINED, NO_CANDIDATES, ERROR, OFFERS, NO_QUALIFIED, ATLAS_INCOMPLETE,
                    REFINED, REFINE_PARTIAL, REFINE_FAILED)

KIND_OPERATOR = "operator"
KIND_OFFERS = "offers"
KIND_REFINEMENT = "options_refinement"
KINDS = (KIND_OPERATOR, KIND_OFFERS, KIND_REFINEMENT)

_APPEND_LOCK = threading.Lock()


def new_outcome_id() -> str:
    return f"out_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:10]}"


def append_outcome(path: Path | None = None, **fields) -> dict:
    """Append one outcome. `state` must be a persisted state and `kind` operator|offers."""
    path = Path(path) if path is not None else OUTCOMES_PATH
    state = fields.get("state")
    if state not in PERSISTED_STATES:
        raise ValueError(f"not a persistable outcome state: {state!r}")
    if fields.get("kind") not in KINDS:
        raise ValueError(f"unknown outcome kind: {fields.get('kind')!r}")
    record = {
        "schema": SCHEMA,
        "outcome_id": fields.pop("outcome_id", None) or new_outcome_id(),
        "at": datetime.now(timezone.utc).isoformat(),
        "source": "new",
        **fields,
    }
    with _APPEND_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_outcomes(path: Path | None = None) -> list[dict]:
    path = Path(path) if path is not None else OUTCOMES_PATH
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _matches(record: dict, *, kind, field, page_id, operator, policy, criteria_version) -> bool:
    if record.get("kind") != kind or record.get("page_id") != page_id:
        return False
    if field is not None and record.get("field") != field:
        return False
    if policy is not None and record.get("policy") != policy:
        return False
    if kind in (KIND_OPERATOR, KIND_REFINEMENT):
        if operator is not None and record.get("operator") != operator:
            return False
        if criteria_version is not None and record.get("criteria_version") not in (None, criteria_version):
            return False
    return True


def state_of_run(result: dict | None) -> str:
    """Outcome state of a recorded Choice run. A run dir only exists when Jev was
    actually asked, so an abstention here is always a real NONE among real candidates."""
    if result is None:
        return ERROR
    if result.get("is_abstention"):
        return ABSTAINED
    return SELECTED


def backfill_from_runs(
    runs_dir: Path,
    *,
    field: str,
    page_id: str,
    operator: str,
    policy: str,
    criteria_version: str,
    exclude_run_ids: set[str] | None = None,
) -> list[dict]:
    """Outcome-shaped views of historical reader run dirs for this exact
    field/page/operator/policy/criteria version. Read-only; nothing is written."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    exclude = exclude_run_ids or set()
    # Reader case ids are "reader-<field>-<page>-<operator>-..."; the name test only
    # avoids parsing hundreds of unrelated input.json files. The record itself decides.
    needle = f"_reader-{field}-{page_id}-{operator.lower()}"
    views = []
    for run_dir in sorted(runs_dir.iterdir()):
        if needle not in run_dir.name or not run_dir.is_dir() or run_dir.name in exclude:
            continue
        try:
            input_record = json.loads((run_dir / "input.json").read_text())
            response = json.loads((run_dir / "response.json").read_text())
            result = json.loads((run_dir / "result.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        reader_state = input_record.get("reader_state") or {}
        if reader_state.get("field") != field or input_record.get("source_id") != page_id:
            continue
        if (reader_state.get("operator") or "").upper() != operator.upper():
            continue
        # Runs recorded before policies/criteria versions existed were unrestricted v0.1.
        if (reader_state.get("policy") or "include-adjacent") != policy:
            continue
        if (reader_state.get("criteria_version") or "v0.1") != criteria_version:
            continue
        candidate_count = len([o for o in input_record.get("option_order") or [] if o != "NONE"])
        run_id = input_record.get("run_id", run_dir.name)
        views.append({
            "schema": SCHEMA,
            "outcome_id": f"run:{run_id}",
            "request_id": None,
            "at": _at_from_run_id(run_id),
            "source": "recorded",
            "kind": KIND_OPERATOR,
            "state": state_of_run(result),
            "field": field,
            "page_id": page_id,
            "page_sha256": (input_record.get("corpus_hashes") or {}).get(page_id),
            "operator": operator.upper(),
            "policy": policy,
            "criteria_version": criteria_version,
            "run_dir": str(run_dir),
            "run_id": run_id,
            "destination": None if result is None else result.get("selected_id"),
            "confidence": None if result is None else result.get("confidence"),
            "candidate_count": candidate_count,
            "mode": "mock" if response.get("live") is False else ("live" if response.get("live") else None),
            "returned_model": response.get("returned_model"),
            "error": response.get("error"),
        })
    return views


def _at_from_run_id(run_id: str) -> str | None:
    try:
        stamp = datetime.strptime(run_id.split("_", 1)[0], "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None
    return stamp.replace(tzinfo=timezone.utc).isoformat()


def outcomes_for(
    *,
    kind: str,
    field: str | None,
    page_id: str,
    operator: str | None = None,
    policy: str | None = None,
    criteria_version: str | None = None,
    runs_dir: Path | None = None,
    path: Path | None = None,
) -> list[dict]:
    """Every outcome for this page (+operator) -- persisted lines plus, for operator
    requests, historical run dirs not already referenced by a line. Newest first."""
    persisted = [
        r for r in read_outcomes(path)
        if _matches(r, kind=kind, field=field, page_id=page_id, operator=operator, policy=policy,
                    criteria_version=criteria_version)
    ]
    combined = list(persisted)
    if kind == KIND_OPERATOR and runs_dir is not None and field and operator and policy and criteria_version:
        referenced = {Path(r["run_dir"]).name for r in persisted if r.get("run_dir")}
        combined += backfill_from_runs(
            runs_dir, field=field, page_id=page_id, operator=operator, policy=policy,
            criteria_version=criteria_version, exclude_run_ids=referenced,
        )
    combined.sort(key=lambda r: r.get("at") or "", reverse=True)
    return combined


# --- plain wording, one sentence per state (the browser renders these via textContent) ---

def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def describe_operator_outcome(outcome: dict) -> str:
    """Distinct wording per state. An abstention says how many real candidates Jev
    declined; an empty candidate list says Jev was never asked."""
    state = outcome.get("state")
    count = outcome.get("candidate_count")
    policy = outcome.get("policy") or "current"
    page = outcome.get("page_id") or "this page"
    if state == SELECTED:
        among = f" among {_plural(count, 'eligible candidate')}" if isinstance(count, int) else ""
        confidence = outcome.get("confidence")
        conf = f" (confidence {confidence})" if confidence is not None else ""
        return f"Jev selected {outcome.get('destination')}{among}{conf}."
    if state == ABSTAINED:
        among = f"all {_plural(count, 'eligible candidate')}" if isinstance(count, int) else "every eligible candidate"
        return (f"Jev was asked and chose NONE: it declined {among}. "
                "An abstention is a recorded answer, not an error and not an empty candidate list.")
    if state == NO_CANDIDATES:
        return (f"No request was made: the {policy} policy leaves no eligible candidate pages for {page}, "
                "so Jev was never asked.")
    if state == ERROR:
        return f"The request failed and nothing was selected: {outcome.get('error') or 'unknown error'}"
    if state == LOADING:
        return "Asking Jev..."
    return "Not requested yet."


def error_text(error) -> str:
    """One plain string for an entry of an offer result's `errors` (a str, or a dict with
    a `message`) -- never a Python repr."""
    if isinstance(error, dict):
        return str(error.get("message") or error.get("status") or "unspecified error")
    return str(error)


def describe_offer_outcome(result: dict) -> str:
    state = result.get("state")
    assessed = len(result.get("assessed_ids") or [])
    not_assessed = result.get("not_assessed_count") or 0
    offered = len(result.get("offers") or [])
    tail = f"({_plural(not_assessed, 'eligible page')} {'was' if not_assessed == 1 else 'were'} not contextually assessed)"
    # Pages with no complete base profile were never candidates at all -- said plainly,
    # never folded into "not contextually assessed".
    incomplete = (result.get("base_counts") or {}).get("ineligible_incomplete")
    partial = ""
    if isinstance(incomplete, int) and not isinstance(incomplete, bool) and incomplete > 0:
        partial = (f" {_plural(incomplete, 'page')} had no complete base profile and could not be considered "
                   "(the base relationship atlas is incomplete for this page).")
    errors = result.get("errors") or []
    failed = [e for e in errors if isinstance(e, dict) and e.get("destination_id")]
    requested = len(result.get("assessed") or []) or (assessed + len(failed))
    failures = ""
    if failed:
        failures = (f" {len(failed)} of {_plural(requested, 'contextual request')} failed "
                    f"(first error: {error_text(failed[0])}).")
    if state == OFFERS:
        return f"{_plural(offered, 'route')} qualified of {assessed} assessed {tail}.{partial}{failures}"
    if state == NO_QUALIFIED and result.get("state_detail") == "empty_shortlist":
        return ("No route qualified: no page's BASE relationship profile cleared the shortlist floors, so nothing "
                f"was sent for contextual assessment. This is a recorded result, not an error.{partial}")
    if state == NO_QUALIFIED:
        return (f"No route qualified: none of the {assessed} contextually assessed pages cleared the thresholds {tail}. "
                f"This is a recorded result, not an error.{partial}{failures}")
    if state == NO_CANDIDATES:
        return (f"No eligible candidate pages from {result.get('page_id') or 'this page'} under the "
                f"{result.get('policy') or 'current'} policy, so nothing was assessed.")
    if state == ATLAS_INCOMPLETE:
        counts = result.get("base_counts") or {}
        detail = ", ".join(f"{k} {v}" for k, v in counts.items() if isinstance(v, (int, float)))
        return ("The base relationship atlas is not complete enough for this page, so no routes can be offered yet"
                + (f" ({detail})." if detail else "."))
    if state == ERROR:
        if failed:
            every = "all" if len(failed) >= requested else f"{len(failed)} of"
            return (f"The offer request failed and no routes are shown: {every} {_plural(requested, 'contextual request')} "
                    f"failed (first error: {error_text(failed[0])}).")
        first = error_text(errors[0]) if errors else (result.get("error") or result.get("state_detail") or "unknown error")
        return f"The offer request failed and no routes are shown: {first}"
    if state == LOADING:
        return "Assessing possible next pages..."
    return "Not requested yet."


# --- ranked operator options: what the ordering is based on, said plainly ---

ORDERING_BASE = "Ordering: base atlas assessments (not yet compared with your reading history)"


def describe_ordering(option_set: dict, *, encounters_supplied: int | None = None, refine_state: str | None = None,
                      order_changed: bool | None = None, no_support: bool = False) -> str:
    """The one line under a ranked option list that says what its order is based on --
    derived from what actually happened, never from intent. A history ordering is claimed
    ONLY when the refinement really changed the order. A failed or partial refinement says
    the order is STILL the base assessments and that nothing was newly assessed."""
    supplied = f" ({_plural(encounters_supplied, 'encounter')} supplied)" if isinstance(encounters_supplied, int) else ""
    none_supported = (" Jev found no support in this history for any of these moves; every option stays available."
                      if no_support else "")
    if option_set.get("ordering_basis") == "reading_history" and refine_state in (None, REFINED):
        shown = len(option_set.get("options") or [])
        if order_changed is False:
            return (f"Ordering: base atlas order \u2014 your reading history was assessed for all {_plural(shown, 'option')}"
                    f"{supplied} but did not change the order.{none_supported}")
        return f"Ordering: your reading history{supplied}.{none_supported}" if none_supported else f"Ordering: your reading history{supplied}"
    if refine_state in (REFINE_PARTIAL, REFINE_FAILED, ERROR):
        return ("Ordering: base atlas assessments \u2014 the history refinement did not complete, so these options "
                "were NOT newly assessed against your reading history")
    return ORDERING_BASE


def describe_refinement(refine_state: str, *, failed: int = 0, shown: int = 0, first_error: str | None = None,
                        order_changed: bool | None = None, no_support: bool = False) -> str:
    detail = f" First error: {first_error}." if first_error else ""
    if refine_state == REFINED:
        none_supported = " Jev found no support in this history for any of these moves." if no_support else ""
        if order_changed is False:
            return (f"Your reading history was assessed for all {_plural(shown, 'option')}, and it did not change the "
                    f"order: this is still the base atlas order.{none_supported} Every option is still here.")
        return f"Order changed using your reading history.{none_supported} Every option is still here; none was removed."
    if refine_state == REFINE_PARTIAL:
        return (f"History refinement was only partly possible ({failed} of {_plural(shown, 'option')} could not be "
                f"assessed), so the base order is kept and every option stays usable.{detail} You can try again.")
    if refine_state == REFINE_FAILED:
        return ("History refinement failed or was refused, so the base order is kept and every option stays "
                f"usable.{detail} You can try again.")
    return f"History refinement could not run; the base order is kept and every option stays usable.{detail} You can try again."


def history_found_no_support(options: list[dict]) -> bool:
    """True when EVERY displayed option's works_after_history answer is at the weakest
    level (nearest level 0, i.e. score < 0.5 on the 0..3 scale)."""
    scores = []
    for option in options or []:
        answers = (option.get("contextual") or {}).get("answers") or {}
        score = (answers.get("works_after_history") or {}).get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            return False
        scores.append(score)
    return bool(scores) and all(int(score + 0.5) == 0 for score in scores)


# --- level words for a base score: the rubric level the score CLEARS, in the rubric's own words ---

_GENERIC_LEVEL_NAMES = ("absent", "slight", "definite", "strong")


def level_cleared(score) -> int | None:
    """>= 2.5 -> 3, >= 2.0 -> 2, >= 1.0 -> 1, else 0. Floors, never rounds: a score below
    the support floor (2.0) can never carry a word that a supported row carries."""
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return None
    if score >= 2.5:
        return 3
    if score >= 2.0:
        return 2
    return 1 if score >= 1.0 else 0


def level_name(dimension: str | None, score) -> str | None:
    level = level_cleared(score)
    if level is None:
        return None
    try:
        from ..atlas import rubrics  # lazy: the atlas package owns the rubric wording

        question = next(q for q in rubrics.get_rubric(rubrics.RUBRIC_VERSION).questions if q.qid == dimension)
        return question.levels[level].split(":", 1)[0].strip().lower()
    except Exception:  # noqa: BLE001 -- the numbers are still shown; only the word falls back
        return _GENERIC_LEVEL_NAMES[level]


def describe_position_conflict(this_page: str | None, logged_page: str | None, action: str) -> str:
    """Truthful wording when the session log places the reader somewhere other than the
    tab that asked. Never advises a reload (which would move this tab to the other page)."""
    here = repr(this_page) if this_page else "this page"
    if logged_page:
        return (f"Nothing was {action} and nothing has moved. This tab shows {here}, but the reading session was last "
                f"recorded on {logged_page!r} (another tab or window moved on). Choose \"Continue here on "
                f"{this_page or 'this page'}\" and then choose the action again yourself, or go to {logged_page!r}.")
    return (f"Nothing was {action} and nothing has moved. The reading session has no recorded visit to {here} yet. "
            f"Choose \"Continue here on {this_page or 'this page'}\" and then choose the action again yourself.")


def describe_option_set(option_set: dict) -> str:
    """Plain status line for a ranked option list, including anything that could not be considered."""
    state = option_set.get("state")
    counts = option_set.get("counts") or {}
    shown = len(option_set.get("options") or [])
    unusable = counts.get("unusable") or 0
    operator = option_set.get("operator") or "this operator"
    parts = []
    if state == "options":
        options = option_set.get("options") or []
        shown_supported = sum(1 for o in options if o.get("tier") == "supported")
        label = (f"{_plural(shown, 'destination')} for {operator}: {shown_supported} supported by the base "
                 f"assessments, {shown - shown_supported} exploratory")
        total_supported = counts.get("supported")
        eligible = counts.get("eligible") or 0
        if isinstance(total_supported, int) and total_supported > shown_supported:
            label += f" ({total_supported} of {_plural(eligible, 'eligible page')} are supported; the strongest are shown)."
        else:
            label += f" (of {_plural(eligible, 'eligible page')})."
        parts.append(label)
    elif state == "fewer_than_three_eligible":
        parts.append(f"Only {_plural(shown, 'destination')} can be shown: fewer than three pages are eligible from "
                     f"{option_set.get('page_id') or 'this page'} under the {option_set.get('policy') or 'current'} policy.")
    elif state == "no_candidates":
        parts.append(f"No pages are eligible from {option_set.get('page_id') or 'this page'} under the "
                     f"{option_set.get('policy') or 'current'} policy, so there is nothing to rank.")
    elif state == "atlas_unavailable" and not option_set.get("error"):
        parts.append("No ranked destinations can be shown: the saved atlas holds no usable base assessment from "
                     f"{option_set.get('page_id') or 'this page'} to any eligible page. Previous, Next and the page list still work.")
    elif state == "atlas_unavailable":
        parts.append("The saved relationship atlas could not be read, so no ranked destinations can be shown: "
                     f"{option_set.get('error') or 'atlas unavailable'}. Previous, Next and the page list still work.")
    else:
        parts.append(f"Unexpected option state {state!r}.")
    if unusable:
        parts.append(f"{_plural(unusable, 'eligible page')} had no usable base assessment and could not be ranked "
                     "(listed in the details; never scored as zero).")
    return " ".join(parts)
