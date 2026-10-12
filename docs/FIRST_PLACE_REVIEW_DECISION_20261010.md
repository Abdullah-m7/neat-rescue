# First-place review decision — Fable 5.1 + Astra Codex

Review date: 10 October 2026. Frozen reviewed commit: dbe44cdf6063f5ccebc64690da320b9432f38960. Both reviewers received the same 117,447-byte source/evidence packet, SHA-256 4abf46882880a68a430d4cdbeca98883188da03dcd5070e0098c5f14a1bb4892. Their first reviews were independent; neither received the other's output. These were static reviews, not model-executed experiments. Controller follow-up checks are distinguished below.

## Verified reviewer identities
- Claude CLI requested `claude-fable-5-1`, high effort. Completed successfully. Provider usage metadata contains `claude-fable-5-1` as well as a Haiku helper. The review was not attributed to a default Opus run.
- Codex CLI 0.154.0 requested `gpt-6-astra`, xhigh effort, read-only sandbox, without user config/MCP setup. Completed successfully. Its matching session turn context records model `gpt-6-astra`, effort `xhigh`, and the isolated review directory. This is CLI/provider-context evidence, not neural-model attestation.

## Shared verdict
Neither reviewer considers the CURRENT entry first-place ready. Both see a defensible bounded repair/acceptance core but an unproved advantage over a direct repair prompt, overly narrow evaluation, and major uncompleted submission evidence. Neither supplies an official score, ranking or win probability.

The official rubric assigns 30% to the agent, 25% to meaningful sponsor use, 20% to video, 15% to public building and 10% to usefulness/originality. All three tools are required. Sponsor use/video/public building total 60%; more synthetic cases cannot substitute for those artifacts.
Source checked 10 October 2026: https://neatlogs.com/hackathon

## Confirmed issues, reproduced by the controller
Astra identified two specific holes in the old verifier. Both were executed, not merely assumed:

| Incorrect source behavior | Old development | Old fresh cases | Concrete contract failure |
|---|---:|---:|---|
| Reject valid order ages zero and one | 80/80 | 128/128 | A one-day-old eligible order returns False |
| Include attempt-ID length in logical operation key | 80/80 | 128/128 | a1 and a10 produce different keys for the same refund |

These invalidate a strong interpretation of an old green gate. They do NOT prove that the three historical model-written patches were wrong.

### Applied correction
Version `blindbench/2.1-boundary-and-retry-coverage` adds explicit zero/one-day cases and both same-length and different-length retry identifiers. Five new regression tests accompany the change. The two incorrect candidates are now rejected: 74/80 and 70/80 respectively; their fresh-set scores are 118/128 and 112/128. The full suite now passes 91 tests.

All three historical accepted source patches were re-evaluated with the corrected verifier and still pass 128/128. Those are NEW, separately recorded checks with NEW case hashes. Original runs and original results were not rewritten.

## Reviewer concerns checked or qualified
1. **CLI isolation:** inspected the exact 22 recorded planner session IDs and only their matching NeatRescue transcripts. All were located. The sole observed tool name was `StructuredOutput`; there were no Read, Bash, file-search or MCP tool calls. Multiple formatting-tool turns also explain the recorded CLI turn-limit failure. This is observed tool-use evidence, not an OS sandbox or proof about every possible process input. Do not describe a no-tools CLI as a security boundary.
2. **Public specification vs leakage:** the public business contract is legitimate task input. Fable called its richness specification leakage; Astra correctly distinguished this from leaked private ground truth. Do not remove necessary business rules merely to handicap a baseline or manufacture an advantage. Use the same public contract in comparative tests.
3. **Recovery:** Astra's repeated-final-evaluation and artifact-lineage concerns remain OPEN. The current recovery path can create multiple children/fresh seeds for the same incomplete parent. It does not fully enforce the manual audit's binding of a patch to the model response and evaluator version. A later recovery must reuse a durable final plan/outcome, not redraw tests until acceptance.
4. **Provenance:** an older checkpoint SHA inside a later commit is not itself corruption. Per-run source hashes and ancestry must be shown before claiming an old execution validates the newest code. The evaluator changed during this review and has an explicit new protocol label.
5. **Statistics and narrative:** no review-generated example numbers are accepted as measurements. In particular, Fable's proposed narration about all 80 cases failing is not supported and must not be used. The always-deny suggestion remains a declared host fixture, not a real customer's PR. The same-provider challenger was in a separate context, not an independent-model replication.

## Additional exploratory direct-prompt check
A separate diagnostic requested one source repair per original incident from `claude-opus-5`, the primary model recorded in the historical planner calls. It received the same public contract and original source, but no probe outcomes, private labels, reference implementation or final seed. The protocol and input selection were saved before these calls. This is a retrospective diagnostic, not a preregistered comparative benchmark.

Outcomes across three sources: one direct proposal passed 128/128 under the corrected verifier; one was rejected for exceeding the supported AST node limit; one request timed out at 100 seconds. No retries or hand-edited rescue were counted as baseline successes. This mixed, tiny sample DOES NOT establish superior reasoning, a reliable win rate or a fair latency advantage for NeatRescue. In particular, runtime/subset failures must not be presented as semantic reasoning failures. The clean takeaway is that direct prompting is a credible comparator and code-correctness numbers alone do not establish our product's added value.

## First-place execution priorities
1. **Complete sponsor and submission evidence in parallel with the technical work.** Actual Neatlogs project traces/readback; genuine Entire build checkpoint/context evidence; cfo.ai-produced pricing/cost/revenue/runway plan with assumptions separated from measurements; a <=180-second video, owner-approved public repo and genuine build posts. Local Doctor and input notes are not sponsor completion. No payment, public posting or account action occurred in this review.
2. **Close the remaining acceptance/recovery gap before a stronger demonstration.** Bind original/candidate/evaluator/protocol identities into one durable final plan. Resume its seed/outcome after failure, forbid repeated chances, and require the recovered patch to match the recorded model proposal. Add negative tests. This is a small artifact-protocol repair, not a new orchestration platform.
3. **One decisive end-to-end comparison, not another expansion of toy functions.** A small fake ledger should commit a side effect, lose its acknowledgement, then receive a retry with changed attempt metadata while a legitimate sibling request must still succeed. Compare the same model and same public task evidence under declared ceilings. Include a plausible incomplete patch. Show the gate refusing it and any genuine counterexample-led revision; do not script a 'model mistake' then call it autonomous recovery. If direct prompting matches repair accuracy, position the product around controlled acceptance, recovery and auditable evidence rather than smarter code generation.

Do NOT add arbitrary-repository repair, a new dashboard, many more agents, 100 near-duplicate examples, or a research-platform redesign before submission. The strongest story is a reviewable source proposal and a verifier that can say 'no', not a promise that code is safe to ship.

## Owner-gated blockers
Real Neatlogs key/cloud access, cfo.ai account/plan export and any subscription decision, registration/check-in evidence, and authorization to publish/submit. These are still unverified. The technical review cannot substitute for them.

## Evidence locations
`evidence/first_place_review_20261010/` contains both full reviewer reports, identity/provenance metadata, the 22-session tool audit, old false-acceptance reproductions, corrected-verifier checks and the direct-prompt diagnostic. No hidden reasoning transcripts are exported.
