"""Structural analysis over the frozen atlas (Core v0.3 plan section 4.7-4.9).

Three pure-Python pieces, none of which calls a model or writes to the atlas:

- `index_manifest`: the ordered page-version / operator coordinate system, with a
  snapshot of the atlas it was taken against. Authored page order, never filesystem or
  `Field.all_ids()` order.
- `projection`: the binary adjacency matrices `M_o` (and the status / value / provenance
  views beside them) computed from the assessment store under one manifest.
- `composition`: ordered two-step operator products with witness enumeration. These are
  relation walks in a frozen projection -- not score-valid navigation, not corpus truth.
"""
