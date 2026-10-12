# Neatlogs Cloud Proof — SFAB / neatHack 2026

**Purpose:** Verify real SDK telemetry delivery. The existing `doctor --local` test passed, but the **hosted probe cannot run before a real scoped project key is provided** (`CREDENTIAL_MISSING`). This is a credential/setup blocker, not a successful cloud trace.

## One safe step on your iPhone (do NOT share keys in chat)

1. Sign in at https://app.neatlogs.com/ and open the NeatRescue project. The known project identifier is `9bd5a161-de24-4cff-8215-eb0af18d1bc7`. Open the project's API-key/settings area and copy a **Project API Key** (not a general user token). If none exists, create one through the official app.
2. Open https://github.com/Abdullah-m7/neat-rescue/settings/secrets/actions in your iPhone browser, signed in to **Abdullah-m7**. Switch to desktop website if the mobile interface hides repository Settings.
3. Select **New repository secret**, name it **`NEATLOGS_API_KEY`** (exact uppercase spelling), paste the key as its value, and save.
4. Return to the chat and say **"حفظت سر Neatlogs في GitHub"**. Do **not** send the API key, screenshots containing it, browser cookies, payment card numbers or tokens.

The key is stored by GitHub as an encrypted Actions secret. It is not placed in Git, source code, markdown or action logs. Only a manually triggered job receives it via its environment.

## What the release controller will do

The workflow `.github/workflows/neatlogs-cloud-proof.yml` is **manual (`workflow_dispatch`) only**, so no repeated paid runs occur on commits. It:

1. Runs the installed stable Neatlogs SDK's local Doctor v2, checking `format_version=neatlogs.doctor/v2`, `runtime.language=python`, `schema_version=2`.
2. Runs `python -m neatlogs doctor --probe --json` with the secret. PASS requires **exact four-span finalized authenticated readback**, not merely HTTP accepted or exporter flushed.
3. Runs a real NeatRescue synthetic ledger replay through `python -m neatrescue.trace_replay --live`. It re-evaluates the recorded faulty source (4 payments), deceptively incomplete fix (1), and accepted source (3) as actual SQLite transactions with retries; records one workflow and three tool spans; reads its unique trace back.
4. Uploads sanitized JSON evidence as a GitHub Actions artifact for review. It **does not** post to X, run a new model call, purchase credits, modify other projects or deploy anything.

The actual application replay is **a real bounded program execution**, but **not a new LLM investigation**. The source patch under test came from the earlier recorded model run. It is a synthetic sandbox, not an actual payment trace.

## Success levels and claims

- **Local PASS:** only SDK fixture capture and bounded app replay worked offline.
- **Hosted Doctor probe PASS:** confirmed one synthetic four-span fixture persisted and read back by the same project key.
- **NeatRescue application readback PASS:** confirmed exact trace ID and returned spans for the real synthetic ledger-verification program. This is the evidence to link in judges' README/video.
- Anything less is marked unverified or a specific failure code. **Never treat a 2xx ingest or `flush=True` alone as proof of persisted cloud telemetry.**

If the true application trace is not readable through the project key without the special Doctor marker, the Doctor can still PASS separately. Ask the owner to inspect the application trace through the authenticated Neatlogs dashboard; do not mislabel Doctor data as an app trace.

## Commands (owner/controller, after the secret exists)

```bash
gh workflow run neatlogs-cloud-proof.yml --repo Abdullah-m7/neat-rescue --ref main
gh run list --repo Abdullah-m7/neat-rescue --workflow neatlogs-cloud-proof.yml --limit 3
```

For a local alternative when the owner has access to the Mac: store `NEATLOGS_API_KEY` in `/Users/3obd/Developer/neat-rescue/.env` with `chmod 600` and run the active project's `.venv/bin/python -m neatlogs doctor --probe --json`; avoid showing or committing the key.

Reference: https://docs.neatlogs.com/sdk/doctor and https://docs.neatlogs.com/sdk/python.
