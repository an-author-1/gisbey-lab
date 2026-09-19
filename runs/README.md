# runs/

One directory per run: requests, responses, measurements, reviews, and event records. See "What to Save for Each Run" in the root `README.md`.

Each run directory (`<UTC timestamp>_<case_id>_<mock|live|error>/`) holds `input.json`,
`response.json`, `result.json`, `report.md`, and `review.json`/`review.md` (pending until
filled in with `gibsey review`). Created by `gibsey run-case`.
