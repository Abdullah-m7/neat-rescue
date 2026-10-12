# From review findings to an enforceable acceptance gate

10 October 2026. Core implementation snapshot: 3d35550. This extends NeatRescue; it does not start a new project or modify the older research repository.

## 1. The final evaluation is no longer a new lottery on recovery

Every new incident origin has one durable `final_plan.json` and one terminal `final_outcome.json`.
The plan binds original source, exact candidate bytes, public contract/incident, private incident record,
versioned evaluator files and Python runtime, accepted model-proposal event, and the matching development result.
The final seed is generated once and persisted before final execution. The saved plan/outcome are protected
by a process-released file lock and flushed atomic writes. Changing code, artifacts, verifier or plan identity
blocks recovery. Missing a plan after a freeze also blocks recovery; it does not allocate another seed.

Both PASS and FAIL are terminal. A completed outcome is read back without another evaluator or random draw.
An interrupted *pure* verification may execute again, but uses the same plan/seed. This is once-only decision
identity, not a claim that CPU instructions execute exactly once. It does not run real payments.

Recovery now resumes the canonical origin in place. It does not mint another child with new tests, does not
rewrite private incident labels as an uploaded source, and keeps `report_before_recovery.json`. Legacy runs
without the new version binding are refused rather than silently re-evaluated using today's code.

## 2. What was tested

115 offline unit/regression tests passed. New coverage includes concurrent finalization, rejection readback,
altered candidate/original/model-proposal records, changed verifier identity, legacy evidence refusal,
deleted plans, changed seeds, and repeated recovery of the same origin. A dedicated subprocess really exits
after the plan is written; the next invocation acquires the released lock and completes the same plan.
Only that newly created test subprocess exits; no unrelated research process is stopped.

On the new successful LIVE model run, two additional readbacks were performed while random generation
and evaluator invocation were replaced with failing sentinels. Both returned the same saved verdict;
plan and outcome bytes remained identical. There was exactly one final execution attempt in this live run.

## 3. A meaningful operational example

The test uses actual SQLite storage, not a list presented as a persisted payment system:

`COMMIT -> acknowledgement lost -> connection close -> connection reopen -> retry -> sibling refund -> other tenant`

It is a synthetic refund ledger. It contains no real customers, payments or production connections. The
connection restart in this scenario is not represented as an operating-system crash; that is a separate
final-gate process-exit regression test.

There are three legitimate logical refunds. The original faulty adapter keys by attempt ID, so retrying
creates a fourth payment row. A plausible incomplete repair keys only by order ID: it prevents duplicate
payment on the reported retry, but wrongly suppresses a different legitimate refund on the same order and
a valid request in another tenant. That proposal is explicitly caller-supplied test data, not a claimed
customer PR or a fabricated model mistake.

| Candidate | Rows for 3 legitimate refunds | Retry-only check | Full ledger contract |
|---|---:|---|---|
| Original attempt-scoped key | 4 | FAIL | FAIL: duplicate amount/stock change |
| Proposed order-only key | 1 | PASS | FAIL: legitimate operations suppressed |
| Investigator's source patch | 3 | PASS | PASS |
| Direct prompt's source patch | 3 | PASS | PASS |

The resulting SQLite databases and SELECT readback were saved in `evidence/ledger_experiment_v1/sqlite/`.
All four candidates used the same scenario seed. Checks cover exact amounts, inventory, logical retry,
sibling and cross-tenant isolation. This is one operational example, not broad reliability evidence.

## 4. The comparison was informative, not a manufactured win

The experiment plan and input hashes were saved before either new model run. Both approaches used the
same primary model (`claude-opus-5`) and the same public business contract, original source and proposed
incomplete fix. The direct prompt received that material immediately; the investigator accessed evidence
through its tools. Diagnostic access and resource ceilings differ, so this is not a budget-matched trial.

The investigator completed in 131.222 seconds with eight model-selected tool decisions and one accepted
source patch. It used actual Entire context and SQLite replay, challenged the order-only proposal, and
passed 128/128 adapter cases plus all ledger invariants through the durable gate.

The direct prompt produced a valid source proposal in 29.744 seconds. It also passed the SAME 128 adapter
cases and the SAME ledger scenario when independently checked afterwards. These durations cover different
workflows. No superior repair intelligence, latency advantage or reliability rate is claimed for NeatRescue.

This result supports the narrow positioning: model-generated repairs still need controlled acceptance,
independent regression evidence and reproducible recovery. It does not show that tool orchestration is
needed to write this particular correct patch. We will not hide the direct-prompt success from the demo.

## 5. Remaining submission gaps

Real Neatlogs project authentication and cloud trace readback, a cfo.ai-produced plan, confirmed check-in,
a public repository/posts and a <=180-second video remain incomplete or owner-gated. No credentials were
invented, no subscriptions or card entry occurred, and nothing was published in this work.

No broad repository-repair, deployment-safety or cryptographic authenticity claim is justified. The source
runs in a restricted AST interpreter. Evidence binding assumes a trusted local filesystem, not a malicious
host administrator with the ability to replace every file and hash.

## Evidence

`evidence/ledger_experiment_v1/SUMMARY.json` is the compact checkpoint. It links the live origin, final plan,
terminal verdict, negative controls, concrete SQLite outputs, comparison and full test result. The live
origin is `20261010T125013Z-7ad05b83`.
