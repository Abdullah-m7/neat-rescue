# neatHack 2026 — NeatRescue public build log

## Project

**NeatRescue** — a bounded AI-agent incident investigator that tests repair proposals against counterexamples, persistent-ledger replays, and an independent acceptance gate. Its design question: **"Did the fix solve the visible problem by breaking legitimate behavior?"**

- **Entry:** Solo; handle **[Abdullah-m7](https://github.com/Abdullah-m7)**. Registered team name **SFAB**, confirmed by the participant in Luma on Oct 12.
- **Public code:** https://github.com/Abdullah-m7/neat-rescue
- **Public demo:** https://neatrescue-demo-2026.onrender.com/
- **Narrated 90-second recorded demonstration:** https://neatrescue-demo-2026.onrender.com/media/NeatRescue_VOICE_CUT_90s.mp4
- **Status:** Public repo and demo reachable. **Not yet formally submitted to neatHack.**

## Stack and actual integration

- Python 3.11; bounded AST source evaluation; SQLite (transaction commit/reopen/retry); Python unit tests; Claude CLI model-driven tool selection.
- **Entire**: agent coding checkpoints and source graph context used in the investigated source trace. Curated evidence in `evidence/ENTIRE_CHECKPOINT.json`.
- **Neatlogs SDK**: local instrumentation of agent, LLM and tool calls. Local Doctor v2 returned PASS on Oct 12 with 4 captured spans. **Cloud delivery to authenticated project is NOT verified.** See `evidence/NEATLOGS_LOCAL_DOCTOR_20261012.json`.
- **cfo.ai**: SFAB participant provided two financial-model exports on Oct 12, now [published unchanged with checksum provenance](docs/cfo_ai/CFO_AI_PROVENANCE.md): a [12-page PDF](docs/cfo_ai/NeatRescue_Team_SFAB_neatHack_2026_Business_Plan.pdf) and a [12-sheet XLSX](docs/cfo_ai/NeatRescue_Team_SFAB_neatHack_2026_Financial_Model.xlsx). The report covers pricing, costs, hypothetical revenue and runway. [Summary](docs/cfo_ai/KEY_FINDINGS.md). Independent cfo.ai dashboard access was not verified.
- Recorded demo rendered with English Kokoro voice-over; cinematic opening image in webpage is a labeled synthetic Adobe Firefly illustration. No real customers or real money.

## Dated build log

### Oct 10, 2026 — Start and source-repair experiments

- Began a new, isolated hackathon repository after the official build began, without importing prebuilt code from another research repository.
- Built sandbox refund workflow, model-selected diagnostics and independent case-based verification.
- Recorded authentic investigated repairs and a direct-prompt comparison. **The direct prompt repaired the same case successfully, too**; no reasoning-quality or runtime superiority is claimed.
- Reproduced a committed payment with lost acknowledgement. The original source produced **4 payments for 3 legitimate refunds**.
- Found that a plausible order-level idempotency repair produced **1 payment** by wrongly suppressing 2 legitimate operations.
- An accepted source patch produced **3 correct payments**, passing all 8 ledger invariants and **128/128** adapter cases.
- Independent adversarial review caught missing test boundaries; strengthened protocol and froze final acceptance provenance.
- Recorded single final evaluation + persistent readback rather than letting failures re-sample test seeds.

### Oct 11, 2026 — Visual narrative and narration

- Prepared cinematic storytelling with a clearer human-cost-to-verifier arc, narration script and time-coded subtitles.
- Rendered synthetic English narration (Kokoro), deliberately not represented as human speech or ElevenLabs.
- Adobe render job did not produce a retrievable edited MP4 despite task acceptance; that was a blocked step, **not** a completed deliverable.

### Oct 12, 2026 — Verified publishing and recovery

- Successfully produced a **90.33-second** narrated H.264/AAC MP4 from actual recorded evidence and verified playback metadata. Saved a silent 140-second backup.
- Reran **115/115** test suite tests on the curated public-source snapshot.
- Reran Neatlogs local Doctor v2 successfully; it reported a 4-span local trace and a 0-drop diagnostic queue. This is **not** proof of an authenticated cloud project trace.
- Performed a content scan and excluded private filesystem paths, local credentials, full private build logs and runtime temporary files from the curated submission export.
- Published public GitHub repository and 90-second video, then deployed a public Render static presentation and independently verified HTTP 200 for page, video, image, and JSON evidence.

## Reviewer-friendly reproduction

```bash
git clone https://github.com/Abdullah-m7/neat-rescue.git
cd neat-rescue
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

For the source and ledger evidence, inspect `evidence/PUBLIC_RESULTS.json` and the replay JSON files. Candidate code is run in a restricted AST interpreter, **not arbitrary real-world CPython projects**.

## Important limits

- **One synthetic four-function incident** with bounded verification; not an estimate of reliability in production or general repository repair.
- No proven autonomous production deployment, no real payments or customers, and no operationally verified cloud Neatlogs trace.
- Local source hashes bind records for consistency; not externally signed attestations.
- The public repository is an intentionally curated snapshot, not a claim that all original private development history has been published.
- The demo is **recorded evidence visualization with synthetic narration**, not a live tool demo. A future improvement should show authenticated sponsor dashboards only after actual integration.

## Official submission gate — still pending as of 12 Oct (KSA)

- [ ] Confirm check-in with the email used on Luma: https://neatlogs.com/hackathon/check-in
- [ ] Record actual Neatlogs authenticated cloud trace URL/screenshot; never commit an API key.
- [x] Record Entire checkpoint and source context.
- [x] Received and publicly archived the two participant-supplied cfo.ai financial exports (PDF and XLSX), including prices, costs, hypothetical revenue and runway. Dashboard-origin receipt not independently confirmed.
- [x] Publish publicly accessible GitHub repo and demo video <=180 seconds.
- [ ] Update demo to explicitly explain verified use of all three sponsors; do not imply unfinished integrations are complete.
- [ ] Publish official quote post on X **during the official window** with registered team name, builder name, repository and demo URL. Capture public X permalink.
- [ ] Confirm final cutoff on event Discord. **Opening the X draft does not submit.**

Official rules: https://neatlogs.com/hackathon ; build skill: https://neatlogs.com/hackathon/skill

*This log records what was observed and accomplished; planned sponsor actions are not described as completed.*

## Oct 12 official organizer submission email (newer than generic rules)

Submission is **TWO mandatory steps** at opening: (1) quote-tweet the announced official @neatlogs launch X post with three accounts tagged in the quote — @neatlogs, @EntireHQ, @arithecfo — and (2) fill the distinct official submission form whose link is released at the same time. Submitting a form alone or omitting a required tag means the automated submission detector will NOT detect the entry. Live schedule: 7–11:55 PM IST, or 4:30–9:25 PM Saudi. Registered team SFAB has been added. Official form submission receipt remains pending. See docs/NEATHACK_FORM_READY.md and docs/X_SUBMISSION_DRAFT.txt.


### Oct 12: Neatlogs real-workflow local replay

- Added a real application-level instrumentation entry point: `python -m neatrescue.trace_replay --local`, with one `WORKFLOW` and three tool wrappers around SQLite commit/reopen/retry checks.
- Verified 4 faulty, 1 incomplete and 3 accepted payments; the accepted candidate passed all 8 independent ledger invariants. **No new model call** is made by this deterministic verification run.
- Published [sanitized replay results](evidence/NEATLOGS_REAL_SYNTHETIC_REPLAY_LOCAL_20261012.json), [source](neatrescue/trace_replay.py) and [project-key setup](docs/NEATLOGS_CLOUD_PROOF_SETUP.md).
- SDK Doctor local v2 PASS; the controlled hosted probe returned `CREDENTIAL_MISSING` because the project API key is not installed. Thus authenticated Neatlogs cloud delivery is **NOT YET confirmed**.
