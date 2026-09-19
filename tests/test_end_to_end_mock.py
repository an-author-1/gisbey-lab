import json

from gibsey_lab.config import Config
from gibsey_lab.context import assemble_f12_micro
from gibsey_lab.corpus import corpus_hashes
from gibsey_lab.runner import run_case


def test_offline_end_to_end_run_is_recorded(tmp_path, synthetic_manifest, synthetic_reviewed_map):
    packet = assemble_f12_micro(synthetic_manifest, synthetic_reviewed_map)
    cfg = Config(model="jev-latest", api_key=None)

    outcome = run_case(
        packet, cfg, mock=True, corpus_hashes=corpus_hashes(synthetic_manifest), runs_dir=tmp_path / "runs"
    )

    assert outcome["ok"] is True
    run_dir = outcome["run_dir"]
    assert run_dir.name.endswith("_f12-micro_mock")

    response = json.loads((run_dir / "response.json").read_text())
    assert response["live"] is False

    report = (run_dir / "report.md").read_text()
    assert "MOCK" in report
    assert "F12.S4" in report  # active passage shown

    review = json.loads((run_dir / "review.json").read_text())
    assert review["decision"] == "undecided"
    assert review["grounding_score"] is None
