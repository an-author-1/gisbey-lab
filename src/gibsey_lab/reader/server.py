"""Minimal local browser reader for Gibsey Lab.

Pure Python standard library (http.server) -- no new dependencies. Bound to 127.0.0.1
only. Reuses gibsey_lab.fields / reader_context / runner / recorder / state /
saved_runs / reviewing unchanged. The only endpoint that ever makes a live Jev call is
POST /api/request-selection, and only in response to an explicit request from the page
(loading the page, switching fields/sources/operators, and viewing saved results never
call it).
"""
from __future__ import annotations

import json
import mimetypes
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import fields as fields_module
from .. import reader_context, relational_operators, saved_runs, state
from ..config import load_config
from ..context import CaseError
from ..fields import FieldError
from ..jev_client import JevError
from ..recorder import RUNS_DIR
from ..reviewing import ReviewError, update_review
from ..runner import run_case
from ..validate import ProviderResultError

STATIC_DIR = Path(__file__).resolve().parent / "static"

# Module-level (not a bound default arg) so tests can point it at a tmp_path without
# ever touching the real project data/ directory.
DATA_DIR = state.DEFAULT_DATA_DIR


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _field_manifest_hashes(field) -> dict[str, str]:
    return {pid: p.sha256 for pid, p in field.manifest.items()}


def _saved_result_to_dict(saved: saved_runs.SavedResult | None) -> dict:
    if saved is None:
        return {"recorded": False}
    return {
        "recorded": True,
        "run_id": saved.run_id,
        "run_dir": str(saved.run_dir),
        "field": saved.field,
        "source": saved.source_id,
        "operator": saved.operator,
        "criterion": saved.criterion,
        "is_abstention": saved.is_abstention,
        "selected_id": saved.selected_id,
        "selected_text": saved.selected_text,
        "confidence": saved.confidence,
        "probabilities": saved.probabilities,
        "requested_model": saved.requested_model,
        "returned_model": saved.returned_model,
        "elapsed_seconds": saved.elapsed_seconds,
        "usage": saved.usage,
    }


def _run_outcome_to_dict(run_dir: Path) -> dict:
    input_record = json.loads((run_dir / "input.json").read_text())
    response = json.loads((run_dir / "response.json").read_text())
    result = json.loads((run_dir / "result.json").read_text())
    return {
        "run_id": input_record["run_id"],
        "run_dir": str(run_dir),
        "field": input_record.get("reader_state", {}).get("field"),
        "source": input_record["source_id"],
        "operator": input_record.get("reader_state", {}).get("operator"),
        "criterion": input_record["criterion"],
        "live": response.get("live"),
        "requested_model": response.get("requested_model"),
        "returned_model": response.get("returned_model"),
        "elapsed_seconds": response.get("elapsed_seconds"),
        "usage": response.get("usage"),
        "error": response.get("error"),
        "result": result,  # None if the run failed/errored
    }


class Handlers:
    """Route implementations, kept separate from HTTP plumbing for testability."""

    @staticmethod
    def get_fields(_query: dict) -> dict:
        return {
            "fields": [
                {"id": fields_module.HOLDOUT_21, "label": "21-page holdout field (London Fox / Princhetta)", "default": True},
                {"id": fields_module.FULL_41, "label": "Complete 41-page corpus (training + holdout)", "default": False},
            ],
            "operators": relational_operators.OPERATOR_NAMES,
            "criteria": relational_operators.CRITERIA,
            "operator_version": relational_operators.VERSION,
        }

    @staticmethod
    def get_pages(query: dict) -> dict:
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        try:
            field = fields_module.load_field(field_id)
        except FieldError as e:
            raise ApiError(str(e)) from e
        return {"field": field.id, "label": field.label, "pages": field.all_ids()}

    @staticmethod
    def get_page(query: dict) -> dict:
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        page_id = query.get("id", [None])[0]
        if not page_id:
            raise ApiError("missing 'id'")
        try:
            field = fields_module.load_field(field_id)
        except FieldError as e:
            raise ApiError(str(e)) from e
        if page_id not in field.manifest:
            raise ApiError(f"page {page_id!r} not in field {field.id!r}", status=404)
        page = field.manifest[page_id]
        return {"field": field.id, "id": page.id, "text": page.text, "sha256": page.sha256}

    @staticmethod
    def get_saved_result(query: dict) -> dict:
        field_id = query.get("field", [fields_module.DEFAULT_FIELD])[0]
        source_id = query.get("source", [None])[0]
        operator = query.get("operator", [None])[0]
        if not source_id or not operator:
            raise ApiError("missing 'source' or 'operator'")
        if field_id != fields_module.HOLDOUT_21:
            # The 41-page combined field has never been exercised by a live experiment;
            # there is nothing to preload, by design.
            return {"recorded": False, "reason": f"field {field_id!r} has no recorded original-field runs"}
        saved = saved_runs.find_saved_original_field_result(source_id, operator.upper())
        return _saved_result_to_dict(saved)

    @staticmethod
    def post_request_selection(body: dict) -> dict:
        field_id = body.get("field", fields_module.DEFAULT_FIELD)
        source_id = body.get("source")
        operator = body.get("operator")
        if not source_id or not operator:
            raise ApiError("missing 'source' or 'operator'")
        try:
            field = fields_module.load_field(field_id)
            packet = reader_context.assemble_reader_packet(field, source_id, operator.upper())
        except (FieldError, CaseError, ValueError) as e:
            raise ApiError(str(e)) from e

        cfg = load_config()
        if not cfg.has_live_credentials:
            raise ApiError("TYPESAFE_API_KEY is not configured; cannot make a live request", status=503)

        outcome = run_case(packet, cfg, mock=False, corpus_hashes=_field_manifest_hashes(field), runs_dir=RUNS_DIR)
        run_dir = outcome["run_dir"]
        record = _run_outcome_to_dict(run_dir)
        if not outcome["ok"]:
            record["error"] = outcome["error"]
        return record

    @staticmethod
    def post_propose(body: dict) -> dict:
        run_dir = Path(body.get("run_dir", ""))
        if not run_dir:
            raise ApiError("missing 'run_dir'")
        try:
            proposal_id = state.propose(run_dir, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        return {"proposal_id": proposal_id}

    @staticmethod
    def post_accept(body: dict) -> dict:
        proposal_id = body.get("proposal_id")
        if not proposal_id:
            raise ApiError("missing 'proposal_id'")
        try:
            bond_id = state.accept(proposal_id, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        return {"bond_id": bond_id}

    @staticmethod
    def post_follow(body: dict) -> dict:
        bond_id = body.get("bond_id")
        if not bond_id:
            raise ApiError("missing 'bond_id'")
        try:
            new_state = state.follow(bond_id, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        return new_state

    @staticmethod
    def post_accept_and_follow(body: dict) -> dict:
        """Convenience action combining propose -> accept -> follow. Each step is still
        recorded through the same, separate state.py functions and files as if invoked
        individually -- this is one button, not one merged record."""
        run_dir = Path(body.get("run_dir", ""))
        if not run_dir:
            raise ApiError("missing 'run_dir'")
        try:
            proposal_id = state.propose(run_dir, data_dir=DATA_DIR)
            bond_id = state.accept(proposal_id, data_dir=DATA_DIR)
            new_state = state.follow(bond_id, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        return {"proposal_id": proposal_id, "bond_id": bond_id, "reader_state": new_state}

    @staticmethod
    def post_preserve(body: dict) -> dict:
        bond_id = body.get("bond_id")
        if not bond_id:
            raise ApiError("missing 'bond_id'")
        try:
            entry_id = state.preserve(bond_id, data_dir=DATA_DIR)
        except state.StateError as e:
            raise ApiError(str(e)) from e
        return {"entry_id": entry_id}

    @staticmethod
    def get_reader_state(_query: dict) -> dict:
        return state.reader_state(data_dir=DATA_DIR)

    @staticmethod
    def post_review(body: dict) -> dict:
        run_dir = Path(body.get("run_dir", ""))
        if not run_dir:
            raise ApiError("missing 'run_dir'")
        try:
            review = update_review(
                run_dir,
                correspondence=body.get("correspondence"),
                reading_effect=body.get("reading_effect"),
                grounding_score=body.get("grounding_score"),
                effect_score=body.get("effect_score"),
                decision=body.get("decision"),
            )
        except ReviewError as e:
            raise ApiError(str(e)) from e
        return review


GET_ROUTES = {
    "/api/fields": Handlers.get_fields,
    "/api/pages": Handlers.get_pages,
    "/api/page": Handlers.get_page,
    "/api/saved-result": Handlers.get_saved_result,
    "/api/reader-state": Handlers.get_reader_state,
}
POST_ROUTES = {
    "/api/request-selection": Handlers.post_request_selection,
    "/api/propose": Handlers.post_propose,
    "/api/accept": Handlers.post_accept,
    "/api/follow": Handlers.post_follow,
    "/api/accept-and-follow": Handlers.post_accept_and_follow,
    "/api/preserve": Handlers.post_preserve,
    "/api/review": Handlers.post_review,
}


class ReaderRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter default logging
        sys.stderr.write(f"[reader] {self.address_string()} {fmt % args}\n")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, rel_path: str) -> None:
        target = (STATIC_DIR / rel_path).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in GET_ROUTES:
            try:
                result = GET_ROUTES[parsed.path](query)
                self._send_json(result)
            except ApiError as e:
                self._send_json({"error": str(e)}, status=e.status)
            except Exception as e:  # noqa: BLE001 -- last-resort guard, never crash the server
                self._send_json({"error": f"{type(e).__name__}: {e}"}, status=500)
            return

        if parsed.path == "/":
            self._send_static("index.html")
        else:
            self._send_static(parsed.path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in POST_ROUTES:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON body"}, status=400)
            return
        try:
            result = POST_ROUTES[parsed.path](body)
            self._send_json(result)
        except ApiError as e:
            self._send_json({"error": str(e)}, status=e.status)
        except (JevError, ProviderResultError) as e:
            self._send_json({"error": str(e)}, status=502)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": f"{type(e).__name__}: {e}"}, status=500)


def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("the reader app must bind to localhost only")
    server = ThreadingHTTPServer((host, port), ReaderRequestHandler)
    url = f"http://{host}:{port}/"
    print(f"Gibsey Lab reader running at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
