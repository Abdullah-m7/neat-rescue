"""One durable final-evaluation identity/outcome per incident.

Trusted local filesystem, not signed attestation against its administrator.
A crash may require repeating PURE verification with the SAME plan/seed; it
must never redraw a seed, silently change a verifier, or replay a real payment.
"""
from __future__ import annotations
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

SUITE = 'neatrescue/final-suite-v1'
PLAN_SCHEMA = 'neatrescue/final-plan-v1'
MODULES = ('blindbench.py', 'bounded_python.py', 'ledger_replay.py', 'final_evaluation.py')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def digest(value):
    return sha(canonical(value))


def read_json(path):
    if path.is_symlink():
        raise ValueError('Symlink not permitted in final-evaluation evidence')
    return json.loads(path.read_text())


def atomic_json(path, value):
    """A fully flushed replacement; interrupted temp writes do not replace truth."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as fp:
            fp.write(json.dumps(value, indent=2, ensure_ascii=False))
            fp.flush(); os.fsync(fp.fileno())
        os.replace(name, path)
        folder = os.open(str(path.parent), os.O_RDONLY)
        try: os.fsync(folder)
        finally: os.close(folder)
    finally:
        if os.path.exists(name): os.unlink(name)


def verifier_identity():
    from . import blindbench, ledger_replay
    folder = Path(__file__).resolve().parent
    return {'suite': SUITE, 'adapter_protocol': blindbench.EVALUATION_PROTOCOL,
            'ledger_protocol': ledger_replay.LEDGER_PROTOCOL,
            'python': sys.version.split()[0], 'implementation': sys.implementation.name,
            'files': {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                      for name in MODULES}}


def evaluate_candidate(source, seed, count):
    from . import blindbench, ledger_replay
    result = blindbench.evaluate(source, seed=seed, count=count)
    ledger = ledger_replay.replay(source, seed=seed)
    # Temp path is an execution detail, not part of a reproducible verdict.
    ledger.pop('database_path', None)
    result['adapter_tests_passed'] = result['passed']
    result['ledger_replay'] = ledger
    result['passed'] = bool(result['adapter_tests_passed'] and ledger['passed'])
    result['evaluation_suite'] = SUITE
    return result


def verify_events(origin):
    path = Path(origin) / 'events.jsonl'
    if path.is_symlink(): raise ValueError('Event log must not be a symlink')
    previous = '0' * 64
    rows = []
    for seq, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip(): raise ValueError('Empty/corrupt event record')
        row = json.loads(line)
        body = dict(row); found = body.pop('event_hash')
        if row.get('seq') != seq or row.get('previous_hash') != previous or digest(body) != found:
            raise ValueError('Event chain integrity failure')
        previous = found; rows.append(row)
    return rows


def development_binding(origin, source, number, result, identity):
    origin = Path(origin)
    before = read_json(origin / 'source_before.json')['source']
    return {'schema': PLAN_SCHEMA, 'patch_number': number, 'source_sha256': sha(source),
            'original_source_sha256': sha(before), 'verifier': identity,
            'public_incident_sha256': digest(read_json(origin / 'public_incident.json')),
            'sealed_incident_sha256': digest(read_json(origin / 'sealed_incident.json')),
            'development_seed': 20261010, 'development_count': result['total'],
            'development_result_sha256': digest(result)}


def inspect_candidate(origin, source, number):
    """Enforce links that previously existed only in a retrospective manual audit."""
    origin = Path(origin)
    if origin.is_symlink(): raise ValueError('Origin must not be a symlink')
    rows = verify_events(origin)
    patch_path = origin / f'patch_{number}.json'
    patch = read_json(patch_path)
    dev = read_json(origin / f'development_{number}.json')
    binding_path = origin / f'development_{number}_binding.json'
    if not binding_path.is_file():
        raise ValueError('Legacy/unbound development result; recovery requires its original recorded protocol')
    binding = read_json(binding_path)
    before = read_json(origin / 'source_before.json')['source']
    sealed = read_json(origin / 'sealed_incident.json')
    public = read_json(origin / 'public_incident.json')
    if patch.get('source') != source or patch.get('sha256') != sha(source):
        raise ValueError('Candidate source does not match saved patch bytes')
    if sealed.get('original_source_sha256') != sha(before):
        raise ValueError('Original source does not match incident identity')
    if dev.get('passed') is not True or dev.get('source_sha256') != sha(source):
        raise ValueError('No passing development result for these source bytes')
    current = verifier_identity()
    expected = development_binding(origin, source, number, dev, current)
    if binding != expected:
        raise ValueError('Development binding, evaluator version or original source changed')
    # Successful proposal -> accepted source -> passing development event, in order.
    proposal = submission = tested = None
    for e in rows:
        data = e.get('data', {})
        if e['kind'] == 'blind_model_decision':
            d = data.get('decision', {})
            if d.get('action') == 'submit_patch' and d.get('source') == source:
                proposal = e; submission = tested = None
        elif e['kind'] == 'blind_tool_result':
            r = data.get('result', {})
            if proposal and data.get('action') == 'submit_patch' and r.get('source_sha256') == sha(source) and r.get('status') == 'UNVERIFIED_SOURCE_PATCH':
                submission = e
            if submission and data.get('action') == 'test_patch' and r.get('passed') is True and digest(r) == digest(dev):
                tested = e
    if not proposal or not submission or not tested:
        raise ValueError('Candidate is not linked to a recorded model proposal and passing test event')
    tools = [e['data'] for e in rows if e['kind'] == 'blind_tool_result' and e['seq'] <= tested['seq']]
    if not any(t.get('action') == 'inspect_source' and t.get('result', {}).get('repository_context_source') == 'Entire graph' for t in tools):
        raise ValueError('Missing successful source-inspection event')
    if not any(t.get('action') == 'probe' and 'by_family' in t.get('result', {}) for t in tools):
        raise ValueError('Missing successful diagnostic probe event')
    if not any(t.get('action') == 'challenge_incoming' and 'independent_validation' in t.get('result', {}) for t in tools):
        raise ValueError('Missing incoming-patch challenge evidence')
    files = ('source_before.json', 'sealed_incident.json', 'public_incident.json',
             f'patch_{number}.json', f'development_{number}.json',
             f'development_{number}_binding.json', 'entire_blind_target_context.json',
             'misleading_patch_challenge.json')
    if any((origin / name).is_symlink() for name in files):
        raise ValueError('Symlinked evidence file')
    evidence = {name: hashlib.sha256((origin / name).read_bytes()).hexdigest() for name in files}
    context = {'origin_run_id': origin.name, 'incident_id': public['incident_id'],
               'candidate_sha256': sha(source), 'original_source_sha256': sha(before),
               'contract_sha256': digest(public['contract']), 'patch_number': number,
               'verifier': current, 'evidence_files': evidence,
               'proposal_event': proposal['event_hash'], 'submission_event': submission['event_hash'],
               'development_event': tested['event_hash']}
    return context, dev


@contextlib.contextmanager
def locked(origin):
    # POSIX flock releases on process death; no PID guessing or stale-lock deletion.
    path = Path(origin) / '.final-evaluation.lock'
    if path.is_symlink(): raise ValueError('Lock path must not be a symlink')
    with path.open('a+') as fp:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def finalize(origin, source, number, journal):
    """Return the same saved verdict, or resume exactly its already saved test plan."""
    origin = Path(origin)
    plan_path = origin / 'final_plan.json'
    outcome_path = origin / 'final_outcome.json'
    with locked(origin):
        if journal.directory.resolve() != origin.resolve():
            raise ValueError('Freeze journal must be the canonical origin')
        context, dev = inspect_candidate(origin, source, number)
        # The caller may have held a stale Journal across another process/crash.
        rows = verify_events(origin)
        journal.events, journal.seq = rows, len(rows)
        journal.chain = rows[-1]['event_hash'] if rows else '0' * 64
        if outcome_path.exists() and not plan_path.exists():
            raise ValueError('Outcome without a final plan; refusing new evaluation')
        if plan_path.exists():
            plan = read_json(plan_path)
            body = dict(plan); found = body.pop('plan_sha256', None)
            if digest(body) != found or plan.get('schema') != PLAN_SCHEMA:
                raise ValueError('Final plan corrupt or incompatible')
            if plan['binding'] != context:
                raise ValueError('Frozen candidate/evidence/verifier changed; no new final chance')
        else:
            if any(e['kind']=='candidate_frozen' for e in rows) or (origin/'final_attempts.json').exists():
                raise ValueError('Missing plan for an existing freeze; refusing seed redraw')
            # Reproduce recorded dev evidence before allocating a final seed.
            reproduced = evaluate_candidate(source, seed=20261010, count=dev['total'])
            if digest(reproduced) != digest(dev) or verifier_identity() != context['verifier']:
                raise ValueError('Recorded development result is not reproducible with this verifier')
            plan = {'schema': PLAN_SCHEMA, 'binding': context, 'count': 128,
                    'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'seed': secrets.randbelow(2**31)}
            plan['plan_sha256'] = digest(plan)
            atomic_json(plan_path, plan)  # Durable BEFORE final test execution.
        frozen_events = [e for e in verify_events(origin) if e['kind'] == 'candidate_frozen']
        if frozen_events:
            if any(e['data'].get('plan_sha256') != plan['plan_sha256'] for e in frozen_events):
                raise ValueError('Final plan does not match recorded freeze identity')
        else:
            journal.emit('candidate_frozen', {'source_sha256': sha(source), 'patch_number': number,
                         'plan_sha256': plan['plan_sha256'], 'verifier_suite': SUITE})
        if outcome_path.exists():
            outcome = read_json(outcome_path)
            body = dict(outcome); found = body.pop('outcome_sha256', None)
            if digest(body) != found or outcome.get('plan_sha256') != plan['plan_sha256']:
                raise ValueError('Final outcome does not match immutable evaluation plan')
            return {'plan': plan, 'outcome': outcome, 'reused_outcome': True}
        attempts_path = origin / 'final_attempts.json'
        attempts = read_json(attempts_path) if attempts_path.exists() else []
        attempts.append({'attempt': len(attempts) + 1, 'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                         'plan_sha256': plan['plan_sha256'], 'seed': plan['seed']})
        atomic_json(attempts_path, attempts)
        result = evaluate_candidate(source, seed=plan['seed'], count=plan['count'])
        if verifier_identity() != context['verifier']:
            raise ValueError('Verifier changed during final execution; saved plan remains locked')
        after, _ = inspect_candidate(origin, source, number)
        if after != context: raise ValueError('Evidence changed during final execution')
        outcome = {'plan_sha256': plan['plan_sha256'], 'seed': plan['seed'],
                   'status': 'VALIDATED_SOURCE_PATCH' if result['passed'] else 'REJECTED_FINAL_VALIDATION',
                   'result': result, 'completed_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
        outcome['outcome_sha256'] = digest(outcome)
        atomic_json(outcome_path, outcome)  # PASS and FAIL are equally sticky.
        return {'plan': plan, 'outcome': outcome, 'reused_outcome': False}
