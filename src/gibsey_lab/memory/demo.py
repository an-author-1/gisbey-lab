"""PR2 arrival-history demonstration: does declared history actually reach the judgment?

Three conditions for the same current page, changing ONLY the declared arrival history:
  A  PR1 -> PR3 -> PR2      B  LF3 -> PR2      C  PR2 with no supplied history

Held constant: the PR2 version, the candidate shortlist and its order (computed ONCE from
base profiles and passed to every condition as `fixed_shortlist`), the offer eligibility
policy, the requested model, both rubrics, and the qualification/ranking policy.

These are demonstration fixtures. They are not the reader's actions, they are never
written to the session log or to the reader's offer-set store, and nothing here proposes,
accepts, or follows a bond. The demonstration is correct if the history verifiably
reaches the provider request and the comparison is reproducible; it neither asserts nor
requires that the offered routes differ between conditions. Whether any difference is
textually meaningful is a separate, human question.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from ..corpus import REPO_ROOT
from ..fields import DEFAULT_POLICY, FULL_41, Field, load_field
from ..scoring import Dispatch
from . import contextual, offers as offers_mod, shortlist as shortlist_mod
from .packet import fixture_packet, model_visible_state

DEMO_DIR = REPO_ROOT / "data" / "demos" / "pr2_memory"
DEMO_PAGE = "PR2"
CONDITIONS = (
    ("a", "A", ["PR1", "PR3", "PR2"]),
    ("b", "B", ["LF3", "PR2"]),
    ("c", "C", ["PR2"]),
)
BANNER = "Demonstration fixtures — not the reader's actions, not accepted bonds"


def run_demo(*, dispatch: Dispatch, mode: str, requested_model: str, field: Field | None = None,
             policy: str = DEFAULT_POLICY, profiles_provider=None, atlas_config_provider=None,
             demo_dir: Path | None = None, reuse_cache: bool = True) -> dict:
    field = field or load_field(FULL_41)
    out_dir = Path(demo_dir) if demo_dir is not None else DEMO_DIR
    page = field.manifest[DEMO_PAGE]

    # The shortlist is computed once, from base profiles only, before any history exists.
    provider = profiles_provider or offers_mod._default_profiles_provider
    profiles = list(provider(DEMO_PAGE, mode))
    rows = {row["destination_id"]: row for row in profiles}
    eligible = [pid for pid in field.eligible_candidate_ids(DEMO_PAGE, policy)
                if rows.get(pid, {}).get("status") == "complete"]
    fixed = shortlist_mod.build_shortlist([rows[pid] for pid in eligible], eligible, page_order=field.all_ids())

    results = {}
    for key, label, path_ids in CONDITIONS:
        packet = fixture_packet(field, path_ids, candidate_policy=policy)
        result = offers_mod.build_offers(
            field, DEMO_PAGE, [], policy=policy, dispatch=dispatch, mode=mode, requested_model=requested_model,
            memory_override=packet, fixed_shortlist=fixed, reuse_cache=reuse_cache,
            profiles_provider=profiles_provider, atlas_config_provider=atlas_config_provider, persist=False,
        )
        result["demo"] = {"condition": label, "declared_path": path_ids, "banner": BANNER,
                          "model_visible_history": model_visible_state(packet)}
        results[key] = result

    shortlist_ids = [e["destination_id"] for e in fixed["entries"]]
    request_hashes = {
        pid: {key: next((a["request_sha256"] for a in results[key]["assessed"] if a["destination_id"] == pid), None)
              for key in results}
        for pid in shortlist_ids
    }
    summary = {
        "schema": "pr2-memory-demo/1",
        "banner": BANNER,
        "at": datetime.now(timezone.utc).isoformat(),
        "page_id": DEMO_PAGE,
        "page_sha256": page.sha256,
        "field": field.id,
        "policy": policy,
        "mode": mode,
        "requested_model": requested_model,
        "held_constant": {
            "shortlist_ids_in_order": shortlist_ids,
            "shortlist_policy": shortlist_mod.SHORTLIST_POLICY_VERSION,
            "offer_policy": offers_mod.OFFER_POLICY_VERSION,
            "contextual_rubric": contextual.CONTEXTUAL_RUBRIC_VERSION,
            "question_ids": list(contextual.QUESTION_IDS),
        },
        "static_base_only": offers_mod.static_ranking(fixed),
        "conditions": {
            key: {
                "condition": results[key]["demo"]["condition"],
                "declared_path": results[key]["demo"]["declared_path"],
                "memory_sha256": results[key]["memory_sha256"],
                "state": results[key]["state"],
                "offers": [o["destination_id"] for o in results[key]["offers"]],
                "assessed_ids": results[key]["assessed_ids"],
                "returned_models": results[key]["versions"]["returned_models"],
                "usage": results[key]["usage"],
                "errors": results[key]["errors"],
            }
            for key in results
        },
        "request_sha256_by_candidate": request_hashes,
        "provider_input_differed_for_every_candidate": all(
            len({h for h in hashes.values() if h}) == len([h for h in hashes.values() if h]) and any(hashes.values())
            for hashes in request_hashes.values()
        ) if request_hashes else None,
        "note": "A difference in offers is neither asserted nor required. Literary usefulness is judged separately.",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    for key, result in results.items():
        (out_dir / f"condition_{key}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "comparison.html").write_text(render_html(summary, results), encoding="utf-8")
    return {**summary, "demo_dir": str(out_dir)}


# --------------------------------------------------------------------------- html

_CSS = """
body{font:15px/1.5 Georgia,serif;margin:0;padding:0 20px 60px;background:#fbfaf7;color:#222}
h1{font-size:22px} h2{font-size:18px;margin-top:36px;border-top:1px solid #ccc;padding-top:18px} h3{font-size:15px}
.banner{background:#7a1f1f;color:#fff;padding:10px 20px;margin:0 -20px 20px;font:bold 14px sans-serif}
.meta,table,code{font:13px/1.4 ui-monospace,Menlo,monospace}
table{border-collapse:collapse;margin:8px 0} th,td{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}
th{background:#eee} .scroll{overflow-x:auto}
.history{background:#fff;border:1px solid #ddd;padding:8px 12px;margin:6px 0}
.history pre{white-space:pre-wrap;font:14px/1.45 Georgia,serif;margin:4px 0;max-height:260px;overflow:auto}
.label{font:12px sans-serif;color:#555} .offer{font-weight:bold} .muted{color:#777}
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value) -> str:
    return "—" if value is None else f"{value:.2f}"


def _condition_html(result: dict) -> str:
    demo = result["demo"]
    history = demo["model_visible_history"]
    parts = [f"<h2>Condition {_e(demo['condition'])}: declared path {_e(' → '.join(demo['declared_path']))}</h2>"]
    parts.append(
        f"<p class='meta'>state: {_e(result['state'])} ({_e(result.get('state_detail'))}) · mode: {_e(result['mode'])} · "
        f"requested model: {_e(result['versions']['requested_model'])} · returned: "
        f"{_e(', '.join(result['versions']['returned_models']) or '—')} · memory_sha256: {_e(result['memory_sha256'][:16])}…</p>"
    )
    parts.append("<h3>Exact history supplied to the provider (no page ids are sent; ids appear only in the heading above)</h3>")
    parts.append(f"<p class='label'>{_e(history['note'])} Current page arrived by: {_e(history['current_page_arrived_by'])}.</p>")
    if not history["encounters"]:
        parts.append("<div class='history muted'>(empty history)</div>")
    for encounter in history["encounters"]:
        parts.append(
            f"<div class='history'><span class='label'>encounter {_e(encounter['order'])} · arrived by: "
            f"{_e(encounter['arrived_by'])}</span><pre>{_e(encounter.get('text') or encounter.get('note'))}</pre></div>"
        )

    offered = {o["destination_id"]: o["rank"] for o in result["offers"]}
    parts.append("<h3>History-conditioned answers per shortlisted candidate (score / confidence)</h3>")
    header = "".join(f"<th>{_e(q)}</th>" for q in contextual.QUESTION_IDS)
    parts.append(f"<div class='scroll'><table><tr><th>candidate</th>{header}<th>qualified</th><th>offered</th>"
                 "<th>cache</th><th>request sha256</th></tr>")
    for assessed in result["assessed"]:
        cells = ""
        for qid in contextual.QUESTION_IDS:
            answer = (assessed.get("answers") or {}).get(qid) or {}
            cells += f"<td>{_num(answer.get('score'))} / {_num(answer.get('confidence'))}</td>"
        pid = assessed["destination_id"]
        qualified = "yes" if assessed["qualified"] else "no: " + "; ".join(assessed["reasons"])
        rank = f"<span class='offer'>#{offered[pid]}</span>" if pid in offered else "—"
        parts.append(
            f"<tr><td>{_e(pid)}</td>{cells}<td>{_e(qualified)}</td><td>{rank}</td>"
            f"<td>{'cached' if assessed['from_cache'] else 'fresh'}</td><td>{_e(assessed['request_sha256'][:16])}…</td></tr>"
        )
    parts.append("</table></div>")

    parts.append("<h3>Resulting offers (history-conditioned) beside the base-only ranking</h3>")
    parts.append("<div class='scroll'><table><tr><th>rank</th><th>history-conditioned offer</th><th>base relation labels</th>"
                 "<th>base-only ranking would offer</th></tr>")
    static = [s for s in result["static_base_only"] if s["would_offer"]]
    for i in range(max(len(result["offers"]), len(static))):
        offer = result["offers"][i] if i < len(result["offers"]) else None
        base = static[i] if i < len(static) else None
        parts.append(
            f"<tr><td>{i + 1}</td><td>{_e(offer['destination_id']) if offer else '—'}</td>"
            f"<td>{_e(', '.join(offer['relation_labels'])) if offer else ''}</td>"
            f"<td>{_e(base['destination_id']) + ' (' + _e(base['best_relation']) + ' ' + _num(base['best_score_norm']) + ')' if base else '—'}</td></tr>"
        )
    parts.append("</table></div>")
    if not result["offers"]:
        parts.append("<p class='muted'>No route was offered in this condition; offers are never padded.</p>")
    if result["errors"]:
        parts.append("<h3>Errors</h3><ul>" + "".join(f"<li>{_e(json.dumps(err, ensure_ascii=False))}</li>" for err in result["errors"]) + "</ul>")
    return "\n".join(parts)


def render_html(summary: dict, results: dict) -> str:
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>{_e(summary['page_id'])} memory demonstration</title><style>{_CSS}</style></head><body>",
        f"<div class='banner'>{_e(BANNER)}</div>",
        f"<h1>{_e(summary['page_id'])}: same page, same shortlist, three declared arrival histories</h1>",
        f"<p class='meta'>mode: {_e(summary['mode'])} · requested model: {_e(summary['requested_model'])} · field: "
        f"{_e(summary['field'])} · offer eligibility policy: {_e(summary['policy'])} · page sha256: "
        f"{_e(summary['page_sha256'][:16])}… · generated {_e(summary['at'])}</p>",
        "<p>Held constant across conditions: page version, shortlist and its order "
        f"(<code>{_e(', '.join(summary['held_constant']['shortlist_ids_in_order']) or 'empty')}</code>), the three questions "
        f"(<code>{_e(summary['held_constant']['contextual_rubric'])}</code>), model, and the qualification/ranking policy "
        f"(<code>{_e(summary['held_constant']['offer_policy'])}</code>). Only the declared history changes. "
        f"{_e(summary['note'])}</p>",
        "<h2>Request hashes: proof the provider input differed</h2>",
        "<div class='scroll'><table><tr><th>candidate</th><th>A</th><th>B</th><th>C</th><th>all different</th></tr>",
    ]
    for pid, hashes in summary["request_sha256_by_candidate"].items():
        present = [h for h in hashes.values() if h]
        differs = "yes" if present and len(set(present)) == len(present) else "no"
        cells = "".join(f"<td>{_e((hashes.get(k) or '—')[:16])}</td>" for k in ("a", "b", "c"))
        parts.append(f"<tr><td>{_e(pid)}</td>{cells}<td>{differs}</td></tr>")
    parts.append("</table></div>")
    if not summary["request_sha256_by_candidate"]:
        parts.append("<p class='muted'>The shortlist is empty under the current base atlas, so no contextual request was made.</p>")
    for key in ("a", "b", "c"):
        parts.append(_condition_html(results[key]))
    parts.append("</body></html>")
    return "\n".join(parts)
