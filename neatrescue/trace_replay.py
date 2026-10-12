"""Instrument a REAL NeatRescue SQLite release-gate replay with Neatlogs.

The replay is deterministic and synthetic. It re-evaluates three real source
files captured in the hackathon, but makes NO new LLM call. This must not be
represented as an autonomous model investigation or production payment trace.

Usage: python -m neatrescue.trace_replay --local
       python -m neatrescue.trace_replay --live  # needs NEATLOGS_API_KEY

The live mode checks an exact trace_id through the authenticated Neatlogs
readback endpoint. It never prints, writes or uploads the project API key.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .ledger_replay import INVARIANT_NAMES, replay

ROOT = Path(__file__).resolve().parent.parent
CASE_FILES = (
    ("faulty", "faulty_adapter.py", 4, False),
    ("incomplete", "proposed_order_only_fix.py", 1, False),
    ("verified", "accepted_source.py", 3, True),
)
TRACE_NAME = "neatrescue.synthetic-refund-acceptance-gate"


def _evaluate(label: str, file_name: str, seed: int = 117) -> dict:
    path = ROOT / "evidence" / file_name
    source = path.read_text(encoding="utf-8")
    report = replay(source, seed=seed)  # real SQLite commit, reopen, retry, verification
    return {
        "candidate": label,
        "protocol": report["protocol"],
        "source_sha256": report["source_sha256"],
        "scenario_sha256": report["scenario_sha256"],
        "payment_rows": len(report["observed"]["payment_rows"]),
        "passed": bool(report["passed"]),
        "passed_invariants": sum(bool(value) for value in report["invariants"].values()),
        "total_invariants": len(INVARIANT_NAMES),
        "committed_row_read_after_reopen": bool(
            report["restart"]["committed_row_visible_after_reopen"]
        ),
        "synthetic": True,
        "no_production_changes": True,
    }


def _readback(trace_id: str, api_key: str, endpoint: str) -> dict:
    # Same authenticated project read path as SDK Doctor, but WITHOUT
    # the synthetic Doctor marker: this is an actual instrumented workflow.
    import requests

    if not re.fullmatch(r"[a-f0-9]{32}", trace_id):
        return {"status": "fail", "reason": "TRACE_ID_UNAVAILABLE"}
    base = endpoint.rstrip("/")
    deadline = time.monotonic() + 36
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{base}/api/traces/v3/{trace_id}",
                headers={"x-api-key": api_key},
                timeout=5,
                allow_redirects=False,
            )
        except requests.RequestException:
            return {"status": "fail", "reason": "READBACK_NETWORK_ERROR"}
        if response.status_code in (202, 404):
            time.sleep(1)
            continue
        if response.status_code in (401, 403):
            return {"status": "fail", "reason": "READBACK_AUTH_FAILED"}
        if response.status_code >= 300:
            return {"status": "fail", "reason": "READBACK_HTTP_ERROR", "http_status": response.status_code}
        try:
            parsed = response.json()
        except ValueError:
            return {"status": "fail", "reason": "READBACK_INVALID_JSON"}
        if not isinstance(parsed, dict):
            return {"status": "fail", "reason": "READBACK_INVALID_SCHEMA"}
        spans = parsed.get("spans")
        names = [s.get("name") for s in spans if isinstance(s, dict)] if isinstance(spans, list) else []
        if parsed.get("_id") != trace_id:
            return {"status": "fail", "reason": "TRACE_ID_MISMATCH"}
        if len(names) < 4:
            return {"status": "fail", "reason": "SPANS_NOT_PRESENT", "readback_span_count": len(names)}
        return {
            "status": "pass",
            "trace_id_matches": True,
            "readback_span_count": len(names),
            "trace_names": [name for name in names if name and name.startswith("neatrescue.")],
        }
    return {"status": "fail", "reason": "READBACK_TIMEOUT"}


def main() -> int:
    parser = argparse.ArgumentParser()
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--local", action="store_true", help="actual replay, local only, no credential")
    choice.add_argument("--live", action="store_true", help="actual replay plus authenticated cloud readback")
    options = parser.parse_args()
    import neatlogs
    import logging
    from opentelemetry import trace as ot_trace
    logging.getLogger('neatlogs').setLevel(logging.WARNING)

    key = os.environ.get("NEATLOGS_API_KEY", "").strip()
    if options.live and not key:
        print(json.dumps({"status": "fail", "reason": "CREDENTIAL_MISSING", "cloud_verified": False}))
        return 3
    endpoint = os.environ.get("NEATLOGS_ENDPOINT", "https://ingest.neatlogs.com")
    neatlogs.init(
        api_key=key if options.live else None,
        endpoint=endpoint,
        workflow_name="neatrescue-refund-verification",
        disable_export=not options.live,
        instrumentations=[],
        tags=["neatHack", "SFAB", "synthetic-replay"],
    )
    logging.getLogger('neatlogs').setLevel(logging.WARNING)
    trace_id = ""
    results = []
    flush_ok = False
    stop_ok = False
    try:
        with neatlogs.trace(TRACE_NAME, kind="WORKFLOW") as root_span:
            context = root_span.get_span_context()
            if context.is_valid:
                trace_id = f"{context.trace_id:032x}"
            for label, file_name, expected_rows, expected_pass in CASE_FILES:
                wrapper = neatlogs.span(
                    kind="TOOL",
                    tool_name="sqlite-replay-" + label,
                    capture_input=False,  # source never sent in a span input
                    capture_output=True,  # only synthetic results are captured
                )(_evaluate)
                summary = wrapper(label, file_name)
                if (
                    summary["payment_rows"] != expected_rows
                    or summary["passed"] is not expected_pass
                    or summary["total_invariants"] != 8
                ):
                    raise AssertionError(f"Unreproducible synthetic acceptance result: {label}")
                results.append(summary)
    finally:
        flush_ok = bool(neatlogs.flush(timeout_millis=8000))
        stop_ok = bool(neatlogs.shutdown(timeout_millis=8000))
    result = {
        "format_version": "neatrescue/neatlogs-live-replay/v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "cloud" if options.live else "local",
        "trace_name": TRACE_NAME,
        "trace_id": trace_id if options.live else None,
        "local_trace_id_valid": bool(re.fullmatch(r'[a-f0-9]{32}', trace_id)),
        "synthetic": True,
        "source": "Actual 3-candidate bounded SQLite replay, NOT a fresh LLM run",
        "model_calls_in_this_replay": 0,
        "cases": results,
        "sdk_flush_returned": flush_ok,
        "sdk_shutdown_returned": stop_ok,
        "cloud_verified": False,
    }
    if options.live:
        check = _readback(trace_id, key, endpoint)
        result["readback"] = check
        result["cloud_verified"] = check["status"] == "pass"
    result["status"] = "pass" if len(results) == 3 and (
        not options.live or result["cloud_verified"]
    ) else "unverified"
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
