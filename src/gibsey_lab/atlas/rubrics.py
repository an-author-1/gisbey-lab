"""Base pair rubrics, versioned.

One Score question per dimension, seven dimensions per directed pair, all batched in one
request. Questions in one request never see each other's answers, so every question's
instructions are self-contained: each names the state's role keys (`source_page`,
`destination_page`) and the direction (destination_page read AFTER source_page).

Guarantees:
- A wording change is a new version. Every registered version is frozen exactly as
  written here; add the next version beside them in RUBRICS_BY_VERSION -- never edit one.
  v1 was the pilot rubric. v2 (active) is v1 with `bridge_relation` rewritten: in the
  pilot, v1's bridge gave middling-to-high levels to same-speaker / same-conceit pairs
  (its level 0 was disjunctive and its upper levels accepted a difference in situation,
  characters, OR context). v2 decides sameness first and requires a difference in
  speaker/characters AND situation. The other six questions are word-for-word v1.
  `Rubric.sha256` is part of the atlas config id, so an accidental edit would make old
  records stale rather than silently pooling them with differently worded ones.
- Levels describe observable textual features (0 absent ... 3 strong). No level or
  instruction mentions corpus page IDs, authored position, or any universal merit scale;
  the model sees only the two texts under their role keys.
- `bridge_relation` is a relation between the two supplied passages. It is NOT a
  generated linking page and NOT QDPI L; nothing here asks the model to write anything.
- The original operator criteria (`relational_operators.py`) are untouched and unrelated.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cached_property

from ..scoring import ScoreQuestion, ScoreRequest

RUBRIC_VERSION = "atlas-rubric-v2"

DIMENSIONS: tuple[str, ...] = (
    "direct_q_fit",
    "echo",
    "development",
    "contradiction",
    "bridge_relation",
    "redundancy",
    "missing_context",
)

REQUEST_KIND = "base_pair"

# The exact shape of the model-visible state: role key -> fields supplied under it.
STATE_LAYOUT: dict[str, list[str]] = {"source_page": ["text"], "destination_page": ["text"]}


@dataclass(frozen=True)
class Rubric:
    version: str
    questions: tuple[ScoreQuestion, ...]

    @property
    def dimensions(self) -> tuple[str, ...]:
        return tuple(q.qid for q in self.questions)

    @cached_property
    def sha256(self) -> str:
        blob = json.dumps(
            {"version": self.version, "questions": [q.to_dict() for q in self.questions]},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def question(self, dimension: str) -> ScoreQuestion:
        for q in self.questions:
            if q.qid == dimension:
                return q
        raise KeyError(dimension)


# Every question opens with the same orientation, because each is evaluated on its own.
_V1_FRAME = (
    "The state holds two literary passages: `source_page`, which the reader has just "
    "finished, and `destination_page`, which the reader would read next. Assess only this "
    "directed step -- reading destination_page AFTER source_page; the reverse step is a "
    "separate question and is not asked here. Judge only from the two supplied texts. "
)

_V1_QUESTIONS: tuple[ScoreQuestion, ...] = (
    ScoreQuestion(
        qid="direct_q_fit",
        instructions=_V1_FRAME + (
            "Question: how well does moving directly from source_page to destination_page "
            "work as a single reading step, with nothing read in between? Look for whether "
            "something specific in source_page -- a question, claim, image, situation, or "
            "line of thought -- is taken up by destination_page, and whether "
            "destination_page can be followed when read straight after source_page without "
            "an intermediate passage. This does not rate the merit of either passage, and "
            "a shared subject alone is not a working step."
        ),
        levels=(
            "No workable direct step: nothing specific in source_page is taken up by "
            "destination_page, or destination_page cannot be followed when read straight "
            "after source_page.",
            "Thin direct step: destination_page can be followed after source_page, but the "
            "only link is a general subject, setting, or mood; no specific element of "
            "source_page is taken up.",
            "Workable direct step: at least one specific element of source_page is taken up "
            "by destination_page, though part of destination_page reads as unconnected to "
            "source_page or needs a link the reader must supply unaided.",
            "Strong direct step: a specific element of source_page is taken up centrally by "
            "destination_page, and destination_page can be followed straight after "
            "source_page with no intermediate passage needed.",
        ),
    ),
    ScoreQuestion(
        qid="echo",
        instructions=_V1_FRAME + (
            "Question: does destination_page return to something specific from "
            "source_page -- a particular phrase, image, sentence or scene structure, or "
            "claim that recurs? Assess the recurrence itself, whether or not "
            "destination_page also adds new material: do not lower the level because the "
            "passages overlap heavily, and do not raise it for a shared topic, tone, or "
            "common vocabulary alone."
        ),
        levels=(
            "No identifiable recurrence: destination_page repeats no specific phrase, image, "
            "structure, or claim from source_page; any similarity is only a shared general "
            "topic or tone.",
            "Faint recurrence: a common word, stock image, or loosely similar idea appears "
            "in both passages, but it could plausibly appear in any two passages on the "
            "subject.",
            "Definite recurrence: at least one distinctive phrase, image, structure, or "
            "claim from source_page identifiably returns in destination_page and can be "
            "pointed to in both texts.",
            "Strong recurrence: a distinctive phrase, image, structure, or claim from "
            "source_page returns in destination_page prominently or more than once, in "
            "closely matching or deliberately varied form, so that a reader arriving from "
            "source_page would recognize the return.",
        ),
    ),
    ScoreQuestion(
        qid="development",
        instructions=_V1_FRAME + (
            "Question: does destination_page develop something specific in source_page -- "
            "extend a particular implication, state a consequence, supply a mechanism, or "
            "change how source_page itself can be understood? Staying on the same topic, "
            "carrying the same narrative or argument onward, or adding incidental detail "
            "is not development of this kind and belongs in the lower levels."
        ),
        levels=(
            "No development: destination_page does not extend, apply, or revise anything "
            "specific in source_page; it is unrelated to it or only shares its subject.",
            "Slight development: destination_page stays on the same subject or carries the "
            "same narrative or argument onward with further incident or detail, but draws "
            "no identifiable implication, consequence, or mechanism out of a specific "
            "element of source_page.",
            "Definite development: destination_page takes one specific claim, situation, or "
            "image from source_page and extends it -- drawing out an implication, stating a "
            "consequence, or supplying a mechanism -- and the element extended can be "
            "pointed to in both texts.",
            "Strong development: extending a specific element of source_page is the main "
            "work of destination_page, and it changes how source_page itself can be "
            "understood, for example by qualifying, deepening, or re-framing the original "
            "claim or situation.",
        ),
    ),
    ScoreQuestion(
        qid="contradiction",
        instructions=_V1_FRAME + (
            "Question: does destination_page challenge a specific claim, assumption, or "
            "relationship stated or implied in source_page? Two passages on the same topic "
            "that differ in mood, or that each separately voice doubt, negation, or "
            "disbelief, are not thereby in conflict: the challenge must engage particular "
            "content of source_page. Shared topic alone belongs in the lower levels."
        ),
        levels=(
            "No contradiction: nothing in destination_page opposes, reverses, or undercuts "
            "a specific claim, assumption, or relationship in source_page.",
            "Slight tension: the passages differ in attitude, tone, or stance on a shared "
            "subject, or each separately voices doubt or negation, but destination_page "
            "does not engage a specific claim, assumption, or relationship from "
            "source_page.",
            "Definite contradiction: destination_page opposes, reverses, or undercuts one "
            "specific claim, assumption, or relationship stated or implied in source_page, "
            "and both sides of the conflict can be pointed to in the texts.",
            "Strong contradiction: destination_page directly and centrally opposes a "
            "specific claim, assumption, or relationship that is central to source_page, so "
            "that the two cannot both be accepted as they stand.",
        ),
    ),
    ScoreQuestion(
        qid="bridge_relation",
        instructions=_V1_FRAME + (
            "Question: do source_page and destination_page present otherwise different "
            "situations, characters, or conceptual contexts that are nonetheless joined by "
            "a defensible connection -- one that can be stated in terms of what each "
            "passage is doing, not merely words or a setting they share? This concerns the "
            "relation between the two supplied passages themselves. It does not concern "
            "any third, linking, or newly written passage, and nothing is to be written or "
            "imagined. If the two passages share the same situation, characters, and "
            "context, there is no difference to bridge and the level is low, however "
            "closely related they are."
        ),
        levels=(
            "No bridge: either the two passages share the same situation, characters, and "
            "context, so there is no difference to connect, or they differ and nothing "
            "defensible connects them.",
            "Weak bridge: the passages differ in situation, characters, or context, and the "
            "only connection is shared vocabulary, a shared setting, or a general theme.",
            "Definite bridge: the passages differ in situation, characters, or conceptual "
            "context, and one connection can be stated in terms of what each passage is "
            "doing -- such as a parallel action, a shared problem, or a common structure of "
            "relationship -- with support that can be pointed to in both texts.",
            "Strong bridge: the passages clearly differ in situation, characters, or "
            "conceptual context, and a connection stated in terms of what each passage is "
            "doing is supported by several specific features of both texts, not by shared "
            "words alone.",
        ),
    ),
    ScoreQuestion(
        qid="redundancy",
        instructions=_V1_FRAME + (
            "Question: for a reader who has just read source_page, how little does "
            "destination_page add? Assess the share of destination_page's events, claims, "
            "images, and information that source_page already supplied. This is about what "
            "is added, not about whether a particular phrase or image recurs: a passage may "
            "repeat a distinctive phrase and still add a great deal (low level), or repeat "
            "no exact wording and still add almost nothing (high level)."
        ),
        levels=(
            "No redundancy: almost everything destination_page provides -- events, claims, "
            "images, information -- is absent from source_page.",
            "Slight redundancy: destination_page restates a small part of what source_page "
            "already gave, and most of its content is new.",
            "Substantial redundancy: a large part of destination_page restates, "
            "paraphrases, or re-presents material already given in source_page, with a "
            "smaller portion of new content.",
            "Near-total redundancy: destination_page gives a reader who has just read "
            "source_page almost nothing new; nearly all of its events, claims, images, or "
            "information were already supplied by source_page.",
        ),
    ),
    ScoreQuestion(
        qid="missing_context",
        instructions=_V1_FRAME + (
            "Question: how much does destination_page depend on material that NEITHER "
            "source_page NOR destination_page supplies -- people, events, terms, or earlier "
            "statements it relies on but that are introduced in neither passage? Material "
            "that source_page does supply is not missing. A high level means the reader "
            "arriving from source_page lacks what destination_page needs."
        ),
        levels=(
            "No missing context: destination_page can be followed using only what it and "
            "source_page supply; every person, event, term, or reference it relies on is "
            "introduced in one of the two passages or needs no introduction.",
            "Minor missing context: destination_page mentions one or two people, events, "
            "terms, or earlier statements that neither passage introduces, but its main "
            "sense remains clear.",
            "Substantial missing context: an important part of destination_page relies on "
            "people, events, terms, or earlier statements that neither passage introduces, "
            "so a reader coming only from source_page must guess at part of its meaning.",
            "Severe missing context: the main sense of destination_page depends on people, "
            "events, terms, or earlier statements that neither passage supplies, so it "
            "cannot be adequately followed after source_page alone.",
        ),
    ),
)

RUBRIC_V1 = Rubric(version="atlas-rubric-v1", questions=_V1_QUESTIONS)

_V2_BRIDGE_RELATION = ScoreQuestion(
    qid="bridge_relation",
    instructions=_V1_FRAME + (
        "Question: are source_page and destination_page spoken by or about different "
        "speakers or characters, in different situations, and nonetheless joined by a "
        "specific connection -- one that can be stated in terms of what each passage is "
        "doing, not merely words, a setting, or a general theme they share? This concerns "
        "the relation between the two supplied passages themselves. It does not concern "
        "any third, linking, or newly written passage, and nothing is to be written or "
        "imagined. First decide whether the two passages share the same speaker or "
        "characters, or the same situation or line of thought: if they do, there is no "
        "difference to bridge, however closely related they are."
    ),
    levels=(
        "Nothing to bridge: the two passages share the same speaker or characters, or the "
        "same situation or line of thought, so there is no difference between them to "
        "connect, however closely related they are.",
        "No real bridge: the passages differ in speaker or characters and in situation, "
        "and nothing connects them beyond shared vocabulary, a shared setting, a general "
        "theme, or a likeness that only holds when stated very abstractly.",
        "Definite bridge: the passages differ in speaker or characters and in situation, "
        "and one specific connection can be stated in terms of what each passage is doing "
        "-- such as a parallel action, a shared problem, or a common structure of "
        "relationship -- with support that can be pointed to in both texts.",
        "Strong bridge: the passages clearly differ in speaker or characters and in "
        "situation, and a specific connection stated in terms of what each passage is "
        "doing is supported by several distinct features of both texts, not by shared "
        "words or a general theme.",
    ),
)

# v2 = v1 with only bridge_relation replaced (same frame, same order).
RUBRIC_V2 = Rubric(
    version="atlas-rubric-v2",
    questions=tuple(_V2_BRIDGE_RELATION if q.qid == "bridge_relation" else q for q in _V1_QUESTIONS),
)

RUBRICS_BY_VERSION: dict[str, Rubric] = {
    RUBRIC_V1.version: RUBRIC_V1,
    RUBRIC_V2.version: RUBRIC_V2,
}


def get_rubric(version: str = RUBRIC_VERSION) -> Rubric:
    try:
        return RUBRICS_BY_VERSION[version]
    except KeyError:
        raise KeyError(f"unknown atlas rubric version: {version!r}; known: {sorted(RUBRICS_BY_VERSION)}") from None


def _text_of(page) -> str:
    return page if isinstance(page, str) else page.text


def build_pair_request(
    source_page, destination_page, requested_model: str, *, rubric_version: str = RUBRIC_VERSION
) -> ScoreRequest:
    """One request for the directed pair source -> destination. `source_page` and
    `destination_page` are corpus `Page` objects (or plain text); only their exact text
    enters the state, under role keys -- never a page ID, path, or order."""
    rubric = get_rubric(rubric_version)
    state = {
        "source_page": {"text": _text_of(source_page)},
        "destination_page": {"text": _text_of(destination_page)},
    }
    return ScoreRequest(kind=REQUEST_KIND, state=state, questions=rubric.questions, requested_model=requested_model)


for _rubric in RUBRICS_BY_VERSION.values():
    if _rubric.dimensions != DIMENSIONS or any(len(q.levels) != 4 for q in _rubric.questions):
        raise AssertionError(f"rubric {_rubric.version} must have one 4-level question per dimension, in order")
