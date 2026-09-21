"""Layer 3: explicit reader memory and history-conditioned route offers.

- `packet`     -- the versioned memory packet, derived from session-log events + manifest.
- `contextual` -- the three history-conditioned Score questions, cache key, append-only store.
- `shortlist`  -- deterministic bounded shortlist over the 40 base pair profiles.
- `offers`     -- the full pipeline from active page to at most three offered routes.
- `demo`       -- the PR2 arrival-history demonstration (fixtures, never reader actions).

Nothing in this package imports `gibsey_lab.atlas` at module import time, makes a provider
call on its own (every call goes through an injected `scoring.Dispatch`), or treats an
assessment as a bond, a human judgment, or a reader preference.
"""
