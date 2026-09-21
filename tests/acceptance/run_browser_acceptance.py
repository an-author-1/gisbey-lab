"""Browser acceptance for the reader's exploration contract, in the ACTUAL frontend.

Drives the locally installed Chrome (Playwright, channel="chrome") against an isolated
reader instance (tests/acceptance/serve_isolated.py): temp session stores, the real live
atlas read-only, provider behaviour mocked and labeled. Never touches the user's session
or port 8765, never makes a live call.

Phase 1 -- all 41 x 4 = 164 page/operator combinations: the control works; >=3 distinct
eligible destinations are displayed; they are exactly what memory.operator_options
computes from the atlas (ids, order, tiers); supported/exploratory is visible; every
displayed destination resolves; every preview shows the exact recorded text; one option
(rotating through positions, so exploratory rows are followed too) can be followed and
the reader lands on the displayed destination; Back returns.

Phase 2 -- interaction scenarios with mocked provider behaviour.

Usage:  .venv/bin/python tests/acceptance/run_browser_acceptance.py [--policy discovery] [--headed]
Writes data/verification/browser_acceptance/<stamp>_<rev>.json and exits 1 on any failure.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

import independent  # noqa: E402 -- sibling module; the oracle deliberately does not import gibsey_lab

REPO = Path(__file__).resolve().parents[2]
OPERATORS = ["ECHO", "DEVELOP", "CONTRADICT", "BRIDGE"]
EXPLORATORY_LABEL = "Exploratory — weak or uncertain fit"
T = 8000  # ms


def norm(text: str) -> str:
    return " ".join(text.split())


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_json(url: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


class Reader:
    def __init__(self, page, base: str, policy: str):
        self.page, self.base, self.policy = page, base, policy

    def open(self):
        self.page.goto(self.base + "/")
        self.page.wait_for_selector("[data-testid=source-id]:not(:empty)", timeout=T)
        if self.page.locator("#policy-select").input_value() != self.policy:
            self.page.select_option("#policy-select", self.policy)

    def source(self) -> str:
        return self.page.locator("[data-testid=source-id]").inner_text().strip()

    def goto_page(self, pid: str):
        if self.source() != pid:
            self.page.select_option("#page-select", pid)
        self.page.wait_for_function(
            "pid => document.querySelector('[data-testid=source-id]').textContent.trim() === pid", arg=pid, timeout=T)

    def click_operator(self, op: str, pid: str):
        self.page.click(f"[data-testid=operator-{op}]")
        self.page.wait_for_function(
            """([op, pid]) => { const l = document.querySelector('[data-testid=options-list]');
                 return l && l.dataset.operator === op && l.dataset.page === pid &&
                        l.querySelectorAll('[data-testid=option-row]').length > 0; }""",
            arg=[op, pid], timeout=T)

    def rows(self) -> list[dict]:
        return self.page.evaluate(
            """() => [...document.querySelectorAll('[data-testid=options-list] [data-testid=option-row]')].map(r => ({
                 destination: r.dataset.destination, tier: r.dataset.tier,
                 tier_text: (r.querySelector('[data-testid=option-tier]') || {}).innerText || '',
                 text: r.innerText,
                 visible: [r, r.querySelector('[data-testid=option-tier]'), r.querySelector('[data-testid=option-follow]'),
                           r.querySelector('[data-testid=option-preview]')].every(e => { if (!e) return false;
                     const b = e.getBoundingClientRect(), c = getComputedStyle(e);
                     return b.width > 0 && b.height > 0 && c.visibility !== 'hidden' && c.display !== 'none' && parseFloat(c.opacity) > 0.1; }),
                 follow_disabled: r.querySelector('[data-testid=option-follow]').disabled }))""")

    def row(self, dest: str):
        return self.page.locator(f"[data-testid=option-row][data-destination={dest}]")

    def ordering_basis(self) -> str:
        return self.page.locator("[data-testid=options-list]").get_attribute("data-ordering-basis") or ""

    def follow(self, dest: str, clicks: int = 1):
        button = self.row(dest).locator("[data-testid=option-follow]")
        if clicks == 2:
            button.dblclick()
        else:
            button.click()
        self.page.wait_for_function(
            "pid => document.querySelector('[data-testid=source-id]').textContent.trim() === pid", arg=dest, timeout=T)

    def back(self, expect: str):
        self.page.click("[data-testid=back-btn]")
        self.page.wait_for_function(
            "pid => document.querySelector('[data-testid=source-id]').textContent.trim() === pid", arg=expect, timeout=T)


def check_combo(reader: Reader, atlas, pid: str, op: str, index: int) -> dict:
    result = {"page": pid, "operator": op, "policy": reader.policy, "problems": []}
    problems = result["problems"]
    eligible = set(independent.eligible(pid, reader.policy))
    oracle = independent.expected_rows(atlas, pid, op, reader.policy)  # from the raw records, not from the app
    expected_rows = [(o["destination"], o["tier"]) for o in oracle]
    try:
        reader.goto_page(pid)
        reader.click_operator(op, pid)
        rows = reader.rows()
        shown = [(r["destination"], r["tier"]) for r in rows]
        result["shown"] = shown
        ids = [d for d, _ in shown]
        if len(eligible) >= 3 and len(ids) < 3:
            problems.append(f"only {len(ids)} options displayed ({len(eligible)} eligible)")
        if len(set(ids)) != len(ids):
            problems.append("duplicate destinations displayed")
        if any(d not in eligible for d in ids):
            problems.append(f"ineligible destination displayed: {[d for d in ids if d not in eligible]}")
        if shown != expected_rows:
            problems.append(f"frontend differs from the independent ranking: shown {shown} expected {expected_rows}")
        for r, o in zip(rows, oracle):
            if not r["visible"]:
                problems.append(f"{r['destination']}: row, tier badge, Preview or Follow is not visible")
            shown_fit = re.search(r"([0-9]+(?:\.[0-9]+)?) of 3", r["text"])
            if not shown_fit or abs(float(shown_fit.group(1)) - round(o["score"], 2)) > 1e-9:
                problems.append(f"{r['destination']}: displayed fit {shown_fit.group(0) if shown_fit else None!r} "
                                f"is not the recorded score {o['score']:.2f}")
            shown_conf = re.search(r"confidence ([0-9]+(?:\.[0-9]+)?)", r["text"])
            if not shown_conf or abs(float(shown_conf.group(1)) - round(o["confidence"], 2)) > 1e-9:
                problems.append(f"{r['destination']}: displayed confidence is not the recorded {o['confidence']:.2f}")
            if (o["score"] >= independent.SUPPORT_LEVEL - 1e-9) != (r["tier"] == "supported"):
                problems.append(f"{r['destination']}: tier {r['tier']} contradicts recorded score {o['score']:.2f}")
        for r in rows:
            want = EXPLORATORY_LABEL if r["tier"] == "exploratory" else "Supported"
            if norm(r["tier_text"]) != want:
                problems.append(f"{r['destination']}: tier text {r['tier_text']!r} != {want!r}")
            if r["follow_disabled"]:
                problems.append(f"{r['destination']}: Follow disabled")
        if reader.ordering_basis() != "base_assessments":
            problems.append(f"ordering basis {reader.ordering_basis()!r} without any refinement")
        for d in ids:  # every displayed destination resolves, and its preview is the exact recorded text
            status = reader.page.evaluate(
                "async d => { const r = await fetch(`/api/page?field=full-41&id=${d}`); const j = await r.json(); return [r.status, j.id]; }", d)
            if status != [200, d]:
                problems.append(f"{d} does not resolve: {status}")
            row = reader.row(d)
            row.locator("[data-testid=option-preview]").click()
            preview = row.locator("[data-testid=option-preview-text]")
            preview.wait_for(state="visible", timeout=T)
            if norm(preview.inner_text()) != norm(independent.vault_text(d)):
                problems.append(f"{d}: preview text is not the recorded page text")
        if ids:
            target = ids[index % len(ids)]
            result["followed"] = target
            result["followed_tier"] = dict(shown)[target]
            reader.follow(target)
            landed = norm(reader.page.locator("#source-text").inner_text())
            if landed != norm(independent.vault_text(target)):
                problems.append(f"after Follow the reader does not show {target}'s recorded text")
            reader.back(pid)
    except PlaywrightTimeout as e:
        problems.append(f"timeout: {str(e).splitlines()[0]}")
    except Exception as e:  # noqa: BLE001 -- recorded as evidence, the run continues
        problems.append(f"{type(e).__name__}: {str(e).splitlines()[0]}")
    result["ok"] = not problems
    return result


def check_session_log(path: Path, followed: list[str]) -> list[str]:
    """Exactly the traversals a person made, each as proposal -> acceptance -> traversal ->
    page view, in order, with no duplicates."""
    if not path.exists():
        return ["no session log was written"] if followed else []
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    problems = []
    traversals = [e.get("destination") for e in events if e.get("event") == "q_traversal"]
    if traversals != followed:
        problems.append(f"{len(traversals)} traversals logged for {len(followed)} follows, or in a different order")
    names = [e["event"] for e in events]
    for i, name in enumerate(names):
        if name == "q_traversal":
            window = names[max(0, i - 3):i + 2]
            if window != ["operator_proposed", "offer_accepted", "accept_and_follow", "q_traversal", "page_viewed"]:
                problems.append(f"follow #{traversals.index(events[i].get('destination')) + 1}: event order {window}")
                break
    seqs = [e.get("seq") for e in events]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        problems.append("seq is not strictly increasing")
    return problems


def scenarios(reader: Reader, base: str, session_log: Path, new_context) -> list[dict]:
    out = []
    page = reader.page

    def provider(mode):
        http_json(base + "/__test/provider", {"mode": mode})

    def counters():
        return http_json(base + "/__test/counters")

    def traversals(dest=None):
        events = [json.loads(line) for line in session_log.read_text().splitlines() if line.strip()]
        return [e for e in events if e.get("event") == "q_traversal" and (dest is None or e.get("destination") == dest)]

    def quiesce():
        """Earlier slow-provider scenarios leave background refinements running (2 s per
        option); wait until the mock provider has been idle for 2.5 s so dispatch counts
        measured by the next scenario are its own."""
        last, stable_since = counters(), time.monotonic()
        while time.monotonic() - stable_since < 2.5:
            time.sleep(0.5)
            now = counters()
            if now != last:
                last, stable_since = now, time.monotonic()

    def run(name, fn):
        record = {"scenario": name, "problems": []}
        quiesce()
        try:
            if page.locator("#policy-select").input_value() != reader.policy:  # each scenario starts on the policy under test
                page.select_option("#policy-select", reader.policy)
            fn(record["problems"], record)
        except PlaywrightTimeout as e:
            record["problems"].append(f"timeout: {str(e).splitlines()[0]}")
        except Exception as e:  # noqa: BLE001
            record["problems"].append(f"{type(e).__name__}: {str(e).splitlines()[0]}")
        finally:
            provider("ok")
        record["ok"] = not record["problems"]
        out.append(record)

    def refine_and_wait(timeout=T):
        page.click("[data-testid=refine-button]")
        page.wait_for_function(
            """() => { const s = document.querySelector('[data-testid=refine-status]');
                 const b = document.querySelector('[data-testid=refine-button]');
                 return s && s.textContent.trim() !== '' && !/running|loading|asking|refining…|\\.\\.\\.$/i.test(s.textContent) && !b.disabled; }""",
            timeout=timeout)

    def usable(problems, pid, op="BRIDGE"):
        reader.click_operator(op, pid)
        if len(reader.rows()) < 3:
            problems.append(f"{pid} {op}: fewer than 3 options afterwards")

    def s_switch(problems, rec):
        provider("slow")
        reader.goto_page("P1"); reader.click_operator("DEVELOP", "P1")
        page.click("[data-testid=refine-button]")
        reader.click_operator("ECHO", "P1")
        page.wait_for_timeout(3500)
        lst = page.locator("[data-testid=options-list]")
        if lst.get_attribute("data-operator") != "ECHO":
            problems.append("a pending DEVELOP refinement replaced the ECHO list")
        if reader.ordering_basis() != "base_assessments":
            problems.append("ECHO list claims a history ordering it never requested")
        if len(reader.rows()) < 3:
            problems.append("ECHO list lost options")
        usable(problems, "P1", "DEVELOP")

    def s_navigate_away(problems, rec):
        provider("slow")
        reader.goto_page("P2"); reader.click_operator("DEVELOP", "P2")
        page.click("[data-testid=refine-button]")
        reader.goto_page("P3")
        page.wait_for_timeout(3500)
        if reader.source() != "P3":
            problems.append(f"reader moved to {reader.source()}")
        lst = page.locator("[data-testid=options-list]")
        if lst.get_attribute("data-page") == "P2" and lst.is_visible():
            problems.append("P2's refined list was applied on P3")
        usable(problems, "P3")

    def s_double_clicks(problems, rec):
        reader.goto_page("F3"); reader.click_operator("ECHO", "F3")
        n = len(reader.rows()); before = counters()["contextual_dispatches"]
        page.locator("[data-testid=refine-button]").dblclick()
        page.wait_for_timeout(1500)
        spent = counters()["contextual_dispatches"] - before
        rec["contextual_dispatches"] = spent
        if spent != n:
            problems.append(f"double click dispatched {spent} contextual requests for {n} options (expected exactly {n})")
        if len(reader.rows()) != n:
            problems.append("refinement changed the number of options")
        dest = reader.rows()[0]["destination"]; prior = len(traversals(dest))
        reader.follow(dest, clicks=2)
        page.wait_for_timeout(800)
        made = len(traversals(dest)) - prior
        rec["traversals_from_double_click"] = made
        if made != 1:
            problems.append(f"double-click Follow recorded {made} traversals")
        reader.back("F3")

    def s_refresh(problems, rec):
        reader.goto_page("LF5"); reader.click_operator("BRIDGE", "LF5")
        shown = [r["destination"] for r in reader.rows()]; before = counters()
        page.reload()
        page.wait_for_selector("[data-testid=source-id]:not(:empty)", timeout=T)
        page.wait_for_timeout(1200)
        if reader.source() != "LF5":
            problems.append(f"after refresh the reader is on {reader.source()}")
        kept = page.locator("#policy-select").input_value()
        rec["policy_after_refresh"] = kept
        if kept != reader.policy:
            problems.append(f"the chosen candidate policy {reader.policy!r} reverted to {kept!r} on refresh")
        if counters() != before:
            problems.append("refresh dispatched provider work")
        restored = [r["destination"] for r in reader.rows()]
        rec["restored"] = restored
        if restored != shown:
            reader.click_operator("BRIDGE", "LF5")
            if [r["destination"] for r in reader.rows()] != shown:
                problems.append("options differ after refresh")
            else:
                rec["note"] = "list not auto-restored; one operator click restored it"

    def failing_provider(mode):
        def fn(problems, rec):
            provider(mode)
            reader.goto_page("PR3"); reader.click_operator("DEVELOP", "PR3")
            shown = [r["destination"] for r in reader.rows()]
            refine_and_wait(timeout=20000)
            rec["refine_status"] = norm(page.locator("[data-testid=refine-status]").inner_text())
            rec["ordering_line"] = norm(page.locator("[data-testid=ordering-line]").inner_text())
            if [r["destination"] for r in reader.rows()] != shown:
                problems.append("options changed or vanished after a failed refinement")
            if reader.ordering_basis() != "base_assessments":
                problems.append("failed refinement is labeled as a reading-history ordering")
            if "base" not in rec["ordering_line"].lower():
                problems.append("ordering line does not say the order is still base assessments")
            if not rec["refine_status"]:
                problems.append("no visible message after the failure")
            provider("ok")
            refine_and_wait()  # recoverable: a retry succeeds
            if reader.ordering_basis() != "reading_history":
                problems.append(f"retry after failure did not apply (basis {reader.ordering_basis()!r})")
            reader.follow(shown[0]); reader.back("PR3")
        return fn

    def s_weak(problems, rec):
        provider("weak")
        reader.goto_page("LF9"); reader.click_operator("CONTRADICT", "LF9")
        before = reader.rows()
        refine_and_wait()
        after = reader.rows()
        if sorted(r["destination"] for r in after) != sorted(r["destination"] for r in before):
            problems.append("a contextual abstention removed options")
        if {r["destination"]: r["tier"] for r in after} != {r["destination"]: r["tier"] for r in before}:
            problems.append("tiers changed under refinement")
        line = norm(page.locator("[data-testid=ordering-line]").inner_text())
        rec["ordering_line"] = line
        unchanged = [r["destination"] for r in after] == [r["destination"] for r in before]
        if unchanged:  # what a person reads must not claim a history ordering that did not happen
            if "did not change" not in line.lower() or "base" not in line.lower():
                problems.append(f"order is unchanged but the visible line reads: {line!r}")
            if page.locator("[data-testid=options-list]").get_attribute("data-order-changed") != "false":
                problems.append("data-order-changed is not 'false' for an unchanged order")
        if "no support" not in norm(page.locator("#options-block").inner_text()).lower():
            problems.append("nothing visible says the history gave no support for any option")
        reader.follow(after[-1]["destination"]); reader.back("LF9")

    def s_pick_none(problems, rec):
        provider("pick_none")
        reader.goto_page("P6"); reader.click_operator("DEVELOP", "P6")
        shown = [r["destination"] for r in reader.rows()]
        page.click("[data-testid=single-pick-button]")
        page.wait_for_function(
            "() => /NONE|abstain/i.test(document.querySelector('[data-testid=single-pick-status]').textContent)", timeout=T)
        rec["single_pick_status"] = norm(page.locator("[data-testid=single-pick-status]").inner_text())[:160]
        if [r["destination"] for r in reader.rows()] != shown:
            problems.append("a single-pick abstention hid or changed the ranked options")
        reader.follow(shown[0]); reader.back("P6")

    def s_session_reload(problems, rec):
        reader.goto_page("F7"); reader.click_operator("ECHO", "F7")
        shown = [r["destination"] for r in reader.rows()]; before = counters()
        context, fresh = new_context()
        try:
            other = Reader(fresh, base, reader.policy)
            other.open()
            fresh.wait_for_timeout(1200)
            rec["page_after_reload"] = other.source()
            if other.source() != "F7":
                problems.append(f"a new browser session opened on {other.source()}, not the last page F7")
            if counters() != before:
                problems.append("session reload dispatched provider work")
            other.goto_page("F7"); other.click_operator("ECHO", "F7")
            if [r["destination"] for r in other.rows()] != shown:
                problems.append("options differ in the reloaded session")
        finally:
            context.close()

    def s_repeat(problems, rec):
        for pid in ["P4", "P5", "P4", "P5", "P4"]:
            reader.goto_page(pid); reader.click_operator("DEVELOP", pid)
            if len(reader.rows()) < 3:
                problems.append(f"{pid}: fewer than 3 options on a repeated encounter")
        dest = reader.rows()[1]["destination"]
        reader.follow(dest); reader.back("P4")
        reader.click_operator("DEVELOP", "P4")
        if len(reader.rows()) < 3:
            problems.append("no options after returning with Back")

    run("switch operators while a refinement is pending", s_switch)
    run("navigate away before the response arrives", s_navigate_away)
    run("double click refine and follow", s_double_clicks)
    run("refresh", s_refresh)
    run("provider error during refinement (MOCK)", failing_provider("error"))
    run("provider timeout during refinement (MOCK)", failing_provider("timeout"))
    run("contextual abstention: every answer weakest (MOCK)", s_weak)
    run("single-pick research abstention NONE (MOCK)", s_pick_none)
    run("session reload in a new browser context", s_session_reload)
    run("repeated encounters with the same page", s_repeat)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="discovery", choices=["discovery", "include-adjacent"])
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--pages", help="comma-separated subset, for debugging")
    parser.add_argument("--scenarios-only", action="store_true", help="skip the 164-combination phase")
    args = parser.parse_args()

    atlas = independent.load_atlas()
    pages = args.pages.split(",") if args.pages else independent.PAGES
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    tmp = Path(tempfile.mkdtemp(prefix="gibsey-acceptance-"))
    server = subprocess.Popen([sys.executable, str(Path(__file__).with_name("serve_isolated.py")), str(tmp), str(port)],
                              cwd=REPO, stdout=subprocess.DEVNULL, stderr=open(tmp / "server.log", "w"))
    console_errors: list[str] = []
    try:
        for _ in range(60):
            try:
                build = http_json(base + "/api/build")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        else:
            raise RuntimeError("isolated reader did not start")

        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=not args.headed)

            def new_context():
                context = browser.new_context()
                pg = context.new_page()
                pg.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
                pg.on("console", lambda m: console_errors.append(f"console.error: {m.text}") if m.type == "error" else None)
                return context, pg

            context, page = new_context()
            reader = Reader(page, base, args.policy)
            reader.open()
            combos, index = [], 0
            for pid in ([] if args.scenarios_only else pages):
                for op in OPERATORS:
                    combos.append(check_combo(reader, atlas, pid, op, index))
                    index += 1
                    if not combos[-1]["ok"]:
                        print(f"FAIL {pid} {op}: {combos[-1]['problems']}", flush=True)
                        reader.open()  # recover the page so one failure cannot cascade
            log_problems = check_session_log(tmp / "data" / "session_log.jsonl", [c.get("followed") for c in combos if c.get("followed")])
            scenario_results = [] if args.pages else scenarios(reader, base, tmp / "data" / "session_log.jsonl", new_context)
            context.close()
            browser.close()
        counters = http_json(base + "/__test/counters")
    finally:
        server.terminate()

    failed = [c for c in combos if not c["ok"]]
    failed_scenarios = [s for s in scenario_results if not s["ok"]]
    followed_exploratory = sum(1 for c in combos if c.get("followed_tier") == "exploratory")
    report = {
        "at": datetime.now(timezone.utc).isoformat(), "build": build, "policy": args.policy,
        "browser": "Chrome via Playwright (channel=chrome, headless)" if not args.headed else "Chrome via Playwright (headed)",
        "isolated_data_dir": str(tmp), "provider": "MOCK only (tests/acceptance/serve_isolated.py); atlas = real live records, read-only",
        "combinations": {"total": len(combos), "passed": len(combos) - len(failed), "failed": len(failed),
                         "with_exploratory_rows": sum(1 for c in combos if any(t == "exploratory" for _, t in c.get("shown", []))),
                         "follows_of_exploratory_rows": followed_exploratory},
        "scenarios": {"total": len(scenario_results), "passed": len(scenario_results) - len(failed_scenarios)},
        "console_errors": console_errors[:40], "mock_counters": counters, "session_log_problems": log_problems,
        "failed_combinations": failed, "scenario_results": scenario_results, "all_combinations": combos,
    }
    out_dir = REPO / "data" / "verification" / "browser_acceptance"
    out_dir.mkdir(parents=True, exist_ok=True)
    rev = (build.get("git_revision") or "unknown")[:10] + ("-dirty" if build.get("dirty") else "")
    out = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{rev}_{args.policy}.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(f"combinations: {report['combinations']}")
    print(f"scenarios: {report['scenarios']}  failed: {[s['scenario'] + ': ' + '; '.join(s['problems']) for s in failed_scenarios]}")
    print(f"console errors: {len(console_errors)}   build: {build}")
    print(f"report: {out}")
    print(f"session log: {log_problems or 'exactly the follows made, each proposal -> acceptance -> traversal -> view'}")
    return 1 if (failed or failed_scenarios or console_errors or log_problems) else 0


if __name__ == "__main__":
    raise SystemExit(main())
