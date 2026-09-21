"""Relationship atlas: independent base profiles for every directed page pair (Layer 1).

Layers are kept structurally apart:
- Layer 1 (`api`, `store`, `rubrics`): one independent seven-dimension Score assessment
  per directed pair A->B. Evidence for possible bonds -- never a bond, a human judgment,
  or a reader preference.
- Layer 2 (`choice_history`): read-only view of historical field-relative Choice runs.
  Those probabilities are relative to the competing candidates of one request and never
  flow into a Layer 1 `dimensions` value.
- `ledger`: the hard budget for live provider attempts (only the lead runs it live).
"""
