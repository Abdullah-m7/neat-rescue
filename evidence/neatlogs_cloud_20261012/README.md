# Authenticated Neatlogs cloud proof — Team SFAB

**Date:** October 12, 2026  
**Project:** NeatRescue / neatHack 2026  
**Verification:** Cloud delivery and readback fully confirmed, **without revealing the project key**.

## Independently reproducible GitHub Actions runs

- [First successful cloud probe and application replay](https://github.com/Abdullah-m7/neat-rescue/actions/runs/38248440577)
- [Second successful replay with actual materialized span names/types](https://github.com/Abdullah-m7/neat-rescue/actions/runs/38249053526)
- [Strict schema and semantic verification — PASS](https://github.com/Abdullah-m7/neat-rescue/actions/runs/38249294070)

The final strict run used source SHA `57ea8508464c8067c6c2523d61392922ce14b12b`. It confirmed the exact persisted trace via an authenticated read from the Neatlogs ingest service, rather than simply a successful local flush.

## Final strict run (verified)

- **Neatlogs SDK 1.4.26, Python 3.11.**
- **Doctor v2 local:** PASS, 4 captured synthetic spans.
- **Doctor hosted probe:** PASS; `visible=true`, `finalized=true`, 4 materialized spans, hierarchy and attributes valid; exact trace `421e0c940da3164c4cf2213bc32877a5`.
- **NeatRescue application trace:** PASS; exact persisted trace `fe957baa16c73e165252a60d1d379042`, status `success`, 4 unique named spans with the expected types:
  - `neatrescue.synthetic-refund-acceptance-gate` — `workflow`
  - `sqlite-replay-faulty` — `tool_call`
  - `sqlite-replay-incomplete` — `tool_call`
  - `sqlite-replay-verified` — `tool_call`
- **Application results:** the actual SQLite restart and retry produced **4** payments (faulty, FAIL), **1** payment (plausible incomplete fix, FAIL) and **3** payments (independently accepted patch, PASS, all 8 ledger invariants).
- **Test suite:** 117/117 PASS in this GitHub Actions run.

## Audit files

- [doctor_local.json](doctor_local.json) — controlled SDK capture.
- [doctor_probe.json](doctor_probe.json) — exact authenticated, finalized cloud readback with detailed diagnostic checks.
- [app_replay.json](app_replay.json) — real bounded NeatRescue replay, signed source hashes, exact cloud trace ID, all source outcomes and persisted node names/types.
- [Instrumented application source](../../neatrescue/trace_replay.py) — no new model call; one controlled workflow + 3 real tool spans.

The above files were copied from the **final strict run's GitHub Actions artifact** and checked for accidental secret strings before public publication. The API key was inserted by the owner into `NEATLOGS_API_KEY`, an encrypted repository Actions secret. **The secret value was not read, printed, copied into files, or published.**

## Claim boundary

This proves that an **instrumented synthetic verification workflow** really persisted and was read back from the authenticated Neatlogs cloud API. It does **not** establish that the original model-run traces (which were produced before key configuration) were uploaded retroactively. The proof replay used pre-existing source patches rather than a fresh LLM call, and made no real payment or deployment. NeatRescue's separate model-driven original run is documented in the technical evidence elsewhere.

To inspect the underlying private trace directly in a dashboard, a judge would need appropriate project access. The publicly visible Actions logs and sanitized readback JSON establish the authenticated success without disclosing project credentials.
