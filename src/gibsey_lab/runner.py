from __future__ import annotations

import time
from pathlib import Path

from . import jev_client, mock_client
from .config import Config
from .context import ContextPacket
from .jev_client import JevError
from .recorder import RUNS_DIR, record_run
from .validate import ProviderResultError, validate_choice_result

MAX_RETRIES = 1
RETRY_SLEEP_SECONDS = 1.0


def run_case(
    packet: ContextPacket,
    cfg: Config,
    *,
    mock: bool,
    corpus_hashes: dict[str, str],
    runs_dir: Path = RUNS_DIR,
) -> dict:
    """Call the (mock or real) adapter, validate, and record. Never raises for
    provider/validation failures — those become a recorded error run instead."""
    retries = 0

    if mock:
        result = mock_client.run_choice_mock(
            state=packet.active_text or packet.source_text,
            instructions=packet.criterion,
            criteria=packet.options,
            option_order=packet.option_order,
            model=cfg.model,
        )
    else:
        result = None
        last_error: str | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                result = jev_client.run_choice(
                    cfg,
                    state=packet.active_text or packet.source_text,
                    instructions=packet.criterion,
                    criteria=packet.options,
                )
                break
            except JevError as e:
                last_error = str(e)
                retries = attempt + 1
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_SLEEP_SECONDS)
        if result is None:
            run_dir = record_run(
                packet=packet, result=None, outcome=None, error=last_error,
                retries=retries, corpus_hashes=corpus_hashes, runs_dir=runs_dir,
            )
            return {"ok": False, "run_dir": run_dir, "error": last_error}

    try:
        outcome = validate_choice_result(packet, result)
    except ProviderResultError as e:
        run_dir = record_run(
            packet=packet, result=result, outcome=None, error=str(e),
            retries=retries, corpus_hashes=corpus_hashes, runs_dir=runs_dir,
        )
        return {"ok": False, "run_dir": run_dir, "error": str(e)}

    run_dir = record_run(
        packet=packet, result=result, outcome=outcome, error=None,
        retries=retries, corpus_hashes=corpus_hashes, runs_dir=runs_dir,
    )
    return {"ok": True, "run_dir": run_dir, "outcome": outcome, "result": result}
