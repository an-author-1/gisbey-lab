"""Browser acceptance for scores, with isolated stores and no provider dispatches."""
from __future__ import annotations

import argparse
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from gibsey_lab.core import fixtures, replay
from gibsey_lab.core.core import Core
from gibsey_lab.fields import load_field

from run_browser_acceptance import IsolatedServer, Reader, free_port, http_json

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 10000


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def session(base, session_id):
    return http_json(f"{base}/api/core/session?session_id={session_id}")


def state_key(view):
    return {key: view[key] for key in ("session_id", "active_page", "active_version", "revision", "encounter_count", "score")}


def post(page, base, route, body, status=200):
    response = page.request.post(base + route, data=body)
    assert response.status == status, (route, response.status, response.text())
    return response.json()


def wait_source(page, source):
    page.wait_for_function("source => document.querySelector('#source-id').textContent.trim() === source", arg=source, timeout=TIMEOUT)


def rows(page):
    return page.locator('[data-testid="option-row"]').evaluate_all("rows => rows.map(row => row.dataset.destination)")


def follow(reader, destination):
    with reader.page.expect_request(lambda request: request.url.endswith("/api/core/execute")) as request:
        reader.row(destination).locator('[data-testid="option-follow"]').click()
    wait_source(reader.page, destination)
    return request.value.post_data_json


def begin_demo(reader, mode):
    previous = reader.session()["session_id"]
    reader.page.click(f'[data-testid="start-{mode}-demo"]')
    reader.page.wait_for_function("previous => document.querySelector('[data-testid=core-session]').dataset.sessionId !== previous", arg=previous)
    wait_source(reader.page, "RX1")
    reader.page.wait_for_selector('[data-testid="option-row"]', timeout=TIMEOUT)
    return reader.session()["session_id"]


def leave_demo(reader, original):
    reader.page.click('[data-testid="leave-demo"]')
    reader.page.wait_for_function("original => document.querySelector('[data-testid=core-session]').dataset.sessionId === original", arg=original)
    reader.page.wait_for_selector('[data-testid="start-recurrence-demo"]:enabled', timeout=TIMEOUT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data/verification/core_v03_session3_demo_2026-09-25")
    args = parser.parse_args()
    output = args.output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    store = output / "isolated-store"
    store.mkdir(parents=True)
    isolated = IsolatedServer(store, free_port())
    report = {"browser": "Chrome via Playwright", "isolated_store": str(store), "browser_observations": [], "api_observations": [], "page_errors": []}
    session_ids = {}
    try:
        report["build"] = isolated.start()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            page = context.new_page()
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
            reader = Reader(page, isolated.base, "discovery")
            reader.open()
            original = reader.session()["session_id"]
            session_ids["literary_neutral"] = original
            reader.click_operator("DEVELOP", reader.source())
            target = rows(page)[0]
            follow(reader, target)
            before = session(isolated.base, original)
            next_page = page.locator("#page-select option").evaluate_all("options => options.map(option => option.value)")
            reader.goto_page(next(page_id for page_id in next_page if page_id != target))
            after = session(isolated.base, original)
            assert after["encounter_count"] == before["encounter_count"] + 1
            assert after["score"]["counter"] == before["score"]["counter"]
            report["browser_observations"].append("Literary neutral Q and page-list relocation share a session; only Q advances its counter.")

            neutral = begin_demo(reader, "neutral")
            session_ids["synthetic_neutral"] = neutral
            follow(reader, "RX3")
            reader.click_operator("ECHO", "RX3")
            neutral_rows = rows(page)
            assert "RX1" in neutral_rows
            page.screenshot(path=str(output / "neutral-early-return.png"), full_page=True)
            reader.goto_page("RX1")
            assert session(isolated.base, neutral)["encounter_count"] == 3
            leave_demo(reader, original)
            assert session(isolated.base, neutral)["score"]["status"] == "exited"
            report["browser_observations"].append("Neutral synthetic RX3 offers immediate return to RX1 and permits page-list relocation; Leave records exit and restores the literary journey.")

            scored = begin_demo(reader, "recurrence")
            session_ids["recurrence"] = scored
            follow(reader, "RX3")
            reader.click_operator("ECHO", "RX3")
            scored_rows = rows(page)
            assert "RX1" not in scored_rows and "RX5" in scored_rows
            assert page.locator('[data-testid="score-exclusions"]').is_visible()
            assert "RX1" in page.locator('[data-testid="score-exclusions"]').inner_text()
            assert page.locator('[data-testid="score-progress"]').get_attribute("data-counter") == "1"
            page.screenshot(path=str(output / "recurrence-early-return-excluded.png"), full_page=True)
            report["comparison"] = {"source": "RX3", "neutral_choices": neutral_rows, "recurrence_choices": scored_rows}
            report["browser_observations"].append("At the same synthetic RX3, recurrence excludes RX1 and shows the explanation and outward progress 1 of 2.")

            fixed = state_key(session(isolated.base, scored))
            for control in ("prev-btn", "next-btn", "back-btn"):
                with page.expect_response(lambda response: response.url.endswith("/api/core/relocate")) as response:
                    page.click(f'[data-testid="{control}"]')
                assert response.value.status == 409
                assert state_key(session(isolated.base, scored)) == fixed
            with page.expect_response(lambda response: response.url.endswith("/api/core/relocate")) as response:
                page.select_option("#page-select", "RX7")
            assert response.value.status == 409
            with page.expect_response(lambda response: response.url.endswith("/api/core/relocate")) as response:
                page.evaluate("history.back()")
            assert response.value.status == 409
            assert state_key(session(isolated.base, scored)) == fixed
            page.goto(isolated.base + "/?page=RX1")
            wait_source(page, "RX3")
            assert state_key(session(isolated.base, scored)) == fixed
            report["browser_observations"].append("Previous, Next, in-app Back, page list and browser Back are refused before arrival; direct URL reload resumes RX3 with unchanged score.")

            for route in ("/api/follow", "/api/follow-offer", "/api/follow-option", "/api/accept-and-follow", "/api/request-selection", "/api/offers", "/api/refine-options"):
                post(page, isolated.base, route, {"session_id": scored}, 409)
            for route in ("/api/operator-options", "/api/saved-result"):
                response = page.request.get(isolated.base + route, params={"session_id": scored, "field": fixtures.FIELD_ID, "page": "RX3", "operator": "ECHO"})
                assert response.status == 409
            assert state_key(session(isolated.base, scored)) == fixed
            report["api_observations"].append("Seven legacy research POST routes and two legacy GET routes return 409 during the demonstration without arrivals or provider dispatch.")

            reader.click_operator("ECHO", "RX3")
            old_offer = post(page, isolated.base, "/api/core/options", {"session_id": scored, "operator": "ECHO"})
            page.click('[data-testid="session-pause"]')
            page.wait_for_selector('[data-testid="session-resume"]', timeout=TIMEOUT)
            assert session(isolated.base, scored)["score"]["counter"] == 1
            page.click('[data-testid="session-resume"]')
            page.wait_for_selector('[data-testid="session-pause"]', timeout=TIMEOUT)
            current = session(isolated.base, scored)
            assert current["score"]["counter"] == 1 and current["encounter_count"] == 2
            stale_offer_result = post(page, isolated.base, "/api/core/execute", {
                "session_id": scored, "offer_set_id": old_offer["offer_set_id"],
                "bond_version_id": old_offer["bonds"][0]["bond_version_id"],
                "expected_revision": current["revision"], "request_id": "pre-pause-offer",
            }, 409)
            assert stale_offer_result["code"] == "unknown_or_stale_offer_set"
            report["browser_observations"].append("Pause and resume retain two encounters and outward counter 1.")
            report["api_observations"].append("Pre-pause offer remains invalid after resume, even when sent with the current revision.")

            assert http_json(isolated.base + "/__test/counters")["contextual_dispatches"] == 0
            report["provider_counters_before_restart"] = http_json(isolated.base + "/__test/counters")
            before_restart = session(isolated.base, scored)
            report["restart_build"] = isolated.restart()
            page.reload()
            wait_source(page, "RX3")
            assert state_key(session(isolated.base, scored)) == state_key(before_restart)
            assert page.locator("#source-text").inner_text() == fixtures.demo_field().manifest["RX3"].text
            report["browser_observations"].append("Server process restart and reload preserve exact RX3 text, session, score configuration, movement, counters and encounters.")

            reader.click_operator("ECHO", "RX3")
            stale_page = context.new_page()
            stale_reader = Reader(stale_page, isolated.base, "discovery")
            stale_reader.open()
            stale_reader.click_operator("ECHO", "RX3")
            accepted = follow(reader, "RX5")
            before_retry = state_key(session(isolated.base, scored))
            assert before_retry["score"]["movement"] == "return"
            duplicate = post(page, isolated.base, "/api/core/execute", accepted)
            assert duplicate["duplicate"] is True
            assert state_key(session(isolated.base, scored)) == before_retry
            reused = post(page, isolated.base, "/api/core/execute", {**accepted, "expected_revision": accepted["expected_revision"] + 1}, 409)
            assert reused["code"] == "request_id_reused"
            with stale_page.expect_response(lambda response: response.url.endswith("/api/core/execute")) as response:
                stale_reader.row("RX5").locator('[data-testid="option-follow"]').click()
            assert response.value.status == 409 and response.value.json()["code"] == "stale_revision"
            assert state_key(session(isolated.base, scored)) == before_retry
            stale_page.close()
            report["browser_observations"].append("A stale second tab cannot follow its old RX3 offer after the first tab reaches RX5.")
            report["api_observations"].append("Identical accepted-action retry returns duplicate before staleness; conflicting request ID returns 409; neither advances score.")

            reader.click_operator("ECHO", "RX5")
            assert rows(page) == ["RX1"]
            page.screenshot(path=str(output / "recurrence-return-available.png"), full_page=True)
            follow(reader, "RX1")
            assert page.locator('[data-testid="score-progress"]').get_attribute("data-status") == "complete"
            page.screenshot(path=str(output / "recurrence-complete.png"), full_page=True)
            journey = http_json(isolated.base + f"/api/core/journey?session_id={scored}")
            assert journey["encounters"][-1]["return_index_distance"] == 3
            assert journey["encounters"][-1]["intervening_encounters"] == 2
            save(output / "recurrence-journey.json", journey)
            inspector = context.new_page()
            inspector.goto(isolated.base + f"/journey?session_id={scored}")
            inspector.wait_for_selector('[data-testid="journey-score-decisions"]', timeout=TIMEOUT)
            inspector.locator('[data-testid="journey-score-decisions"]').evaluate_all("details => details.forEach(detail => detail.open = true)")
            assert "return_spacing_satisfied" in inspector.locator("#score-inspection").inner_text()
            assert "candidate_arrival_index" in inspector.locator("#score-inspection").inner_text()
            inspector.locator("#score-inspection p").filter(has_text="return_spacing_satisfied").first.evaluate("element => element.scrollIntoView({block: 'start'})")
            inspector.screenshot(path=str(output / "journey-rule-inspection.png"))
            inspector.close()
            report["browser_observations"].append("RX5 permits RX1; Follow completes recurrence. Journey inspector exposes the rule, encounter references, candidate index 3, index distance 3 and two intervening encounters.")
            leave_demo(reader, original)

            blocked = begin_demo(reader, "recurrence")
            session_ids["blocked_ended"] = blocked
            page.click('[data-testid="operator-CONTRADICT"]')
            page.wait_for_function("document.querySelector('[data-testid=score-progress]').dataset.status === 'blocked'", timeout=TIMEOUT)
            assert page.locator('[data-testid="score-end"]').is_visible()
            page.screenshot(path=str(output / "recurrence-blocked.png"), full_page=True)
            reader.click_operator("ECHO", "RX1")
            page.wait_for_function("document.querySelector('[data-testid=score-progress]').dataset.status === 'active'", timeout=TIMEOUT)
            page.click('[data-testid="operator-CONTRADICT"]')
            page.wait_for_function("document.querySelector('[data-testid=score-progress]').dataset.status === 'blocked'", timeout=TIMEOUT)
            page.click('[data-testid="score-end"]')
            page.wait_for_function("document.querySelector('[data-testid=score-progress]').dataset.status === 'ended_by_reader'", timeout=TIMEOUT)
            leave_demo(reader, original)
            report["browser_observations"].append("Choosing an unavailable operator shows blocked without relaxing rules; End this performance records reader ending, and Leave restores the literary journey.")
            report["provider_counters_after_restart"] = http_json(isolated.base + "/__test/counters")
            assert all(report[name][key] == 0 for name in ("provider_counters_before_restart", "provider_counters_after_restart") for key in ("contextual_dispatches", "single_pick_dispatches"))
            assert not report["page_errors"]
            browser.close()

        report["replays"] = {}
        for name, session_id in session_ids.items():
            core = Core(core_dir=store / "data/core", field=load_field("full-41") if name == "literary_neutral" else fixtures.demo_field())
            bundle = replay.export_bundle(session_id, core, output / "bundles")
            result = replay.replay_bundle(bundle)
            assert result["ok"], result
            report["replays"][name] = result
        report["sessions"] = session_ids
        report["ok"] = True
    except Exception:
        report["ok"] = False
        report["failure"] = traceback.format_exc()
        raise
    finally:
        isolated.stop()
        save(output / "report.json", report)
        print(output / "report.json")


if __name__ == "__main__":
    main()
