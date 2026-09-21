"""Session-log guarantees the reader relies on: append-only, monotonically increasing
`seq` that continues from legacy lines, thread-safe appends."""
import json
import threading

from gibsey_lab import session_log


LEGACY_LINES = [
    {"at": "2026-09-20T03:17:58+00:00", "event": "page_viewed", "field": "full-41", "page_id": "PR4", "from_page": None},
    {"at": "2026-09-20T03:18:13+00:00", "event": "page_viewed", "field": "full-41", "page_id": "PR1", "from_page": None},
    {"at": "2026-09-20T03:18:28+00:00", "event": "accept_and_follow", "field": "full-41", "source": "PR1", "destination": "PR2"},
]


def _write_legacy(path):
    path.write_text("".join(json.dumps(line) + "\n" for line in LEGACY_LINES), encoding="utf-8")


def test_seq_continues_from_legacy_lines_without_rewriting_them(tmp_path):
    log = tmp_path / "session_log.jsonl"
    _write_legacy(log)
    before = log.read_text(encoding="utf-8")

    a = session_log.append_event("page_viewed", log_path=log, field="full-41", page_id="PR2", page_sha256="x", policy="discovery")
    b = session_log.append_event("back", log_path=log, field="full-41", page_id="PR1")
    assert (a["seq"], b["seq"]) == (3, 4)
    assert log.read_text(encoding="utf-8").startswith(before)  # old lines byte-for-byte untouched

    raw = session_log.read_events(log)
    assert "seq" not in raw[0] and raw[3]["seq"] == 3
    with_seq = session_log.read_events_with_seq(log)
    assert [e["seq"] for e in with_seq] == [0, 1, 2, 3, 4]  # monotonic across legacy + new
    assert with_seq[0]["seq_source"] == "line_index" and "seq_source" not in with_seq[3]


def test_seq_stays_correct_when_something_else_appends_in_between(tmp_path):
    log = tmp_path / "session_log.jsonl"
    assert session_log.append_event("page_viewed", log_path=log, page_id="P1")["seq"] == 0
    with open(log, "a", encoding="utf-8") as f:  # another writer (an older reader process, a CLI)
        f.write(json.dumps({"event": "page_viewed", "page_id": "P2"}) + "\n")
    assert session_log.append_event("page_viewed", log_path=log, page_id="P3")["seq"] == 2


def test_a_caller_cannot_choose_its_own_seq(tmp_path):
    log = tmp_path / "session_log.jsonl"
    assert session_log.append_event("page_viewed", log_path=log, seq=99)["seq"] == 0


def test_concurrent_appends_get_unique_contiguous_seqs(tmp_path):
    log = tmp_path / "session_log.jsonl"
    _write_legacy(log)
    threads = [threading.Thread(target=lambda i=i: [session_log.append_event("page_viewed", log_path=log, page_id=f"P{i}") for _ in range(10)])
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = session_log.read_events(log)
    assert len(events) == 3 + 80  # nothing lost, nothing interleaved into a broken line
    assert [e["seq"] for e in events[3:]] == list(range(3, 83))


def test_legacy_traversal_reader_still_works_and_last_encounter_is_computed(tmp_path):
    log = tmp_path / "session_log.jsonl"
    _write_legacy(log)
    session_log.append_event("q_traversal", log_path=log, field="full-41", source="PR1", destination="PR2")
    session_log.append_event("back", log_path=log, field="full-41", page_id="PR1")
    assert [t["destination"] for t in session_log.read_recent_traversals(log_path=log)] == ["PR2"]
    assert session_log.last_encounter(log, field="full-41")["page_id"] == "PR1"
    assert session_log.last_encounter(tmp_path / "missing.jsonl") is None
