# Authenticated Neatlogs cloud proof — 12 October 2026

**Project:** NeatRescue · Team SFAB · neatHack 2026.

**Public, successfully completed CI run:**
https://github.com/Abdullah-m7/neat-rescue/actions/runs/38248440577

The `NEATLOGS_API_KEY` was supplied via an **encrypted GitHub Actions repository secret** and was never included in source code or the uploaded evidence. The key value is not reproduced here.

## Exact results

- **SDK:** Neatlogs Python `1.4.26`, controlled Doctor v2 local capture **PASS**, 4 synthetic spans.
- **Cloud controlled probe:** Doctor v2 `--probe` **PASS**, `probe.visible=true`, `probe.finalized=true`, `probe.readback_span_count=4`, proper hierarchy and attributes. Trace ID: `b76016d3465634304f7ccb39493140c5`.
- **Actual NeatRescue replay:** Three bounded real SQLite commit/reopen/retry verifications, wrapped in a Neatlogs workflow/tool instrumentation. Server returned **exact same trace ID** `e114fb65c336971cb35100d08b44b0ac` with **4 materialized spans**; `app_replay.json` reports `cloud_verified=true`.
- **Independent code tests:** `117/117` unit tests passed in that CI job.
- **Replay outcomes:** original faulty source created **4** payment rows (FAIL), deceptive partial fix created **1** (FAIL), accepted patch created **3** (PASS with 8/8 SQLite invariants).

These are synthetic business fixtures, **not real customer payments**. The trace replay re-evaluates already captured model-authored source. **No fresh LLM call was made during this cloud-proof run**, and it does not assert production-grade agent safety. All financial cfo.ai figures are likewise hypothetical.

## Saved evidence

- [doctor_local.json](doctor_local.json) — local SDK capture diagnostics.
- [doctor_probe.json](doctor_probe.json) — authenticated, materialized Doctor trace and detailed validation flags.
- [app_replay.json](app_replay.json) — actual bounded NeatRescue application replay, unique trace ID, payment rows and cloud-readback status.

The source files are left unchanged except for an independently reviewed tracer wrapper. The original CI artifact `neatrescue-sfab-neatlogs-proof` is downloadable from the successful GitHub Actions run (GitHub retains it for 7 days). This folder makes the evidence durable inside the public repository.

**Provenance note:** readback requires the project's API key. Public visitors can audit the CI logs and checks but cannot query private trace details without project credentials. Never publish the key or an authenticated dashboard session.
