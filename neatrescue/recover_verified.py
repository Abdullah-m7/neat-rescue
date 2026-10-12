"""Resume an origin's durable final plan in place, never create another chance.

Legacy runs without version-bound development evidence are refused. A saved
PASS or FAIL is read back, not rerun. Interrupted pure verification reuses the
same source, verifier, count and seed. No live planner or payment is invoked.
"""
from __future__ import annotations
import argparse
import fcntl
import json
from pathlib import Path
import re
import time
from .investigator import Journal, load_local_environment
from . import final_evaluation as gate

ROOT = Path(__file__).resolve().parents[1]


def recover(parent_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', parent_id):
        raise ValueError('Invalid run id')
    origin = ROOT / 'runs' / parent_id
    if not origin.is_dir() or origin.is_symlink():
        raise ValueError('Unknown origin run')
    lock_path = origin / '.recovery.lock'
    if lock_path.is_symlink(): raise ValueError('Invalid recovery lock')
    with lock_path.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _recover_locked(origin, parent_id)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _recover_locked(origin, parent_id):
    previous_report = gate.read_json(origin / 'report.json')
    if previous_report.get('status') not in ('INCOMPLETE', 'VALIDATED_SOURCE_PATCH', 'REJECTED_FINAL_VALIDATION'):
        raise ValueError('Run is not recoverable or terminal')
    patches = sorted(origin.glob('patch_[0-9].json'))
    if not patches: raise ValueError('No saved candidate source')
    number = int(patches[-1].stem.split('_')[-1])
    source = gate.read_json(patches[-1])['source']
    context, development = gate.inspect_candidate(origin, source, number)
    # No compatibility migration here: do not silently run old evidence with a new verifier.
    if previous_report['status'] != 'INCOMPLETE' and not (origin / 'final_outcome.json').is_file():
        raise ValueError('Terminal report has no bound final outcome')
    load_local_environment()
    import neatlogs, os
    key = os.environ.get('NEATLOGS_API_KEY', '').strip()
    if key.startswith('<'): key = ''
    neatlogs.init(api_key=key or None, endpoint='https://ingest.neatlogs.com',
                  workflow_name='resume-verified-repair', instrumentations=[], disable_export=not bool(key))
    started = time.monotonic()
    try:
        with neatlogs.trace('resume-verified-repair', kind='WORKFLOW'):
            journal = Journal.resume(parent_id)
            backup = origin / 'report_before_recovery.json'
            if not backup.exists(): gate.atomic_json(backup, previous_report)
            journal.emit('checkpoint_resume_requested', {'origin_run_id': parent_id,
                'candidate_sha256': context['candidate_sha256'], 'new_model_calls': 0,
                'external_tool_replays': 0, 'final_seed_redraw_allowed': False})
            operation = neatlogs.span(kind='TOOL', tool_name='resume-same-final-evaluation',
                                     capture_input=False, capture_output=False)(gate.finalize)
            gated = operation(origin, source, number, journal)
            plan, outcome = gated['plan'], gated['outcome']
            public = gate.read_json(origin / 'public_incident.json')
            report = {'status': outcome['status'], 'run_id': parent_id,
                'incident_id': public['incident_id'], 'source_sha256': gate.sha(source),
                'baseline': gate.read_json(origin / 'baseline.json'),
                'development': development, 'fresh_generated': outcome['result'],
                'fresh_seed': plan['seed'], 'patch_count': number,
                'final_plan_sha256': plan['plan_sha256'],
                'final_outcome_sha256': outcome['outcome_sha256'],
                'final_outcome_reused': gated['reused_outcome'],
                'recovery_origin_run_id': parent_id, 'new_model_decisions': 0,
                'external_tool_replays': 0, 'recovery_elapsed_s': round(time.monotonic()-started, 3),
                'code_repair_not_config_selection': True, 'production_modified': False,
                'claim_boundary': 'Resumes one version-bound, pure verification plan under a trusted local filesystem. Not a signed attestation or a production-payment recovery guarantee.'}
            journal.save('report.json', report)
            journal.save('sealed_final_validation.json', {'seed': plan['seed'], 'result': outcome['result'],
                'plan_sha256': plan['plan_sha256'], 'outcome_sha256': outcome['outcome_sha256']})
            journal.emit('terminal', {'status': report['status'], 'origin_run_id': parent_id,
                'final_plan_sha256': plan['plan_sha256'], 'same_saved_outcome': gated['reused_outcome']})
            return report
    finally:
        neatlogs.flush(timeout_millis=5000); neatlogs.shutdown(timeout_millis=5000)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run_id')
    args = p.parse_args()
    result = recover(args.run_id)
    print(json.dumps({'status': result['status'], 'run_id': result['run_id'],
                      'final_plan_sha256': result['final_plan_sha256'],
                      'same_saved_outcome': result['final_outcome_reused']}))
    raise SystemExit(0 if result['status'] == 'VALIDATED_SOURCE_PATCH' else 2)
