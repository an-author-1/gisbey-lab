"""Pure case specifications: no corpus or filesystem access. See context.py for assembly."""
from __future__ import annotations

MAX_OPTIONS = 255  # documented TypeSafe Choice limit

ABSTAIN_ID = "NONE"
ABSTAIN_TEXT = "Abstain: no eligible option supports a defensible correspondence."

MICRO_CASE_ID = "f12-micro"
MICRO_SOURCE_ID = "F12"
MICRO_ACTIVE_ID = "F12.S4"
MICRO_EXCLUDED_NEIGHBORS = ("F12.S3", "F12.S5")
MICRO_ELIGIBLE_IDS = ["F12.S1", "F12.S2", "F12.S6", "F12.S7", "F12.S8", "F12.S9"]
MICRO_CRITERION = (
    "Which eligible sentence, when read beside F12.S4, most clearly changes, sharpens, "
    "or complicates our reading through a specific correspondence grounded in the supplied "
    "text? Shared topic alone is insufficient. Choose NONE if no eligible sentence supports "
    "a defensible correspondence."
)

MACRO_CASE_ID = "f12-macro"
MACRO_SOURCE_ID = "F12"
MACRO_CRITERION = (
    "Which eligible page, when read beside F12, most clearly changes, sharpens, or "
    "complicates our reading of it through a specific correspondence grounded in the "
    "supplied text? Shared topic alone is insufficient. Choose NONE if no eligible page "
    "supports a defensible correspondence."
)

KNOWN_CASE_IDS = (MICRO_CASE_ID, MACRO_CASE_ID)
