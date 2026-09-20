"""Q Operator wording, versioned.

v0.1 is frozen exactly as introduced -- do not edit it. See
notes/q-operator-prototype-v0.1.md for its versioning record and evidence base.

v0.2 addresses a specific problem observed in v0.1 usage: DEVELOP frequently selected
the immediate next authored page (ordinary continuation), which is a weak, largely
positional signal rather than a specific developed implication. See
notes/q-operator-prototype-v0.2.md for the full rationale and bounded-sample comparison.
v0.2 is the reader's active version for new requests; v0.1 remains fully inspectable and
its historical runs/results are unchanged.
"""
from __future__ import annotations

V0_1_CRITERIA: dict[str, str] = {
    "ECHO": (
        "Select the passage that most strongly returns to, mirrors, resonates with, or "
        "meaningfully recurs from the source passage. Choose NONE if no candidate offers "
        "a meaningful echo."
    ),
    "DEVELOP": (
        "Select the passage that most productively extends, complicates, develops, or "
        "transforms what the source passage is doing. Choose NONE if no candidate offers "
        "a productive development."
    ),
    "CONTRADICT": (
        "Select the passage that most meaningfully resists, reverses, destabilizes, "
        "challenges, or creates tension with the source passage. Choose NONE if no "
        "candidate creates meaningful tension."
    ),
    "BRIDGE": (
        "Select the passage that creates the strongest useful connection to the source "
        "that is not primarily based on obvious surface similarity, repeated wording, or "
        "direct thematic overlap. Choose NONE if no candidate offers such a connection."
    ),
}

V0_2_CRITERIA: dict[str, str] = {
    "ECHO": (
        "Select the passage that shares a specific, identifiable textual correspondence "
        "with the source passage -- a phrase, image, structure, or claim that recurs -- "
        "where that return has an identifiable reading effect: something it changes, "
        "intensifies, or clarifies about how the source is understood. A shared topic or "
        "vague thematic similarity alone is not sufficient. Choose NONE if no candidate "
        "offers such a correspondence."
    ),
    "DEVELOP": (
        "Select the passage that extends a specific implication of the source, introduces "
        "a concrete consequence or mechanism arising from it, or changes how the source "
        "itself can be understood. Ordinary continuation of the narrative or the addition "
        "of incidental detail alone should not dominate the choice -- prefer a candidate "
        "that does one of the above over one that merely continues or restates. Choose "
        "NONE if no candidate does this."
    ),
    "CONTRADICT": (
        "Select the passage that challenges a specific claim, assumption, or relationship "
        "stated or implied in the source passage. Two passages that each separately "
        "express doubt, negation, or disbelief are not automatically in tension with each "
        "other -- the challenge must engage the source's specific content, not merely "
        "share a register of denial. Choose NONE if no candidate does this."
    ),
    "BRIDGE": (
        "Select the passage that establishes a defensible connection between situations, "
        "characters, or conceptual contexts that are otherwise different from the "
        "source's -- a connection explainable in terms of what the two passages are "
        "actually doing, not just words they share. Shared vocabulary or setting alone is "
        "not sufficient, and crossing between different authored texts is not itself a "
        "mark of quality. Choose NONE if no candidate offers such a connection."
    ),
}

CRITERIA_BY_VERSION: dict[str, dict[str, str]] = {
    "v0.1": V0_1_CRITERIA,
    "v0.2": V0_2_CRITERIA,
}

DEFAULT_VERSION = "v0.2"

# Backward-compatible aliases: existing callers that import CRITERIA/VERSION get the
# reader's active version. Anything that needs a specific version explicitly should use
# CRITERIA_BY_VERSION[...] instead.
CRITERIA = CRITERIA_BY_VERSION[DEFAULT_VERSION]
VERSION = DEFAULT_VERSION

OPERATOR_NAMES = list(V0_1_CRITERIA)  # ["ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"]
