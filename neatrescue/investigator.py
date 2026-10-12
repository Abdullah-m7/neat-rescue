"""Bounded, model-driven incident investigation. No production side effects."""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]

def load_local_environment() -> None:
    path = ROOT / '.env'
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        if key in {'NEATLOGS_API_KEY', 'NEATLOGS_ENDPOINT', 'NEATRESCUE_MODEL'}:
            os.environ.setdefault(key, value.strip().strip('\"\''))

def canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def digest(obj: object) -> str:
    return hashlib.sha256(canonical(obj).encode()).hexdigest()

class Journal:
    """Unique run directory, append-only action log, explicit terminal status."""
    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.run_id):
            raise ValueError('Invalid run id')
        self.directory = ROOT / 'runs' / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.seq = 0
        self.chain = '0' * 64
        self.events: list[dict] = []

    def emit(self, kind: str, data: dict) -> dict:
        self.seq += 1
        event = {'seq': self.seq, 'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                 'kind': kind, 'data': data, 'previous_hash': self.chain}
        self.chain = digest(event)
        event['event_hash'] = self.chain
        with (self.directory / 'events.jsonl').open('a') as fp:
            fp.write(canonical(event) + '\n')
            fp.flush()
            os.fsync(fp.fileno())
        self.events.append(event)
        print(canonical({'event': kind, 'seq': self.seq, 'data': data}), flush=True)
        return event

    def save(self, name: str, data: dict | list) -> None:
        if Path(name).name != name:
            raise ValueError('Artifact name must be a basename')
        from .final_evaluation import atomic_json
        atomic_json(self.directory / name, data)

    @classmethod
    def resume(cls, run_id: str):
        from .final_evaluation import verify_events
        if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id):
            raise ValueError('Invalid run id')
        folder = ROOT / 'runs' / run_id
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError('Invalid origin run directory')
        rows = verify_events(folder)
        obj = cls.__new__(cls)
        obj.run_id, obj.directory, obj.events = run_id, folder, rows
        obj.seq = len(rows)
        obj.chain = rows[-1]['event_hash'] if rows else '0' * 64
        return obj

def compact_verification(report: dict) -> dict:
    keys = ('passed', 'total', 'passes', 'failures', 'false_refunds', 'missed_refunds',
            'duplicate_payments', 'unexpected_cents', 'first_failures', 'failure_cases',
            'cases_sha256', 'counterexamples')
    return {k: report[k] for k in keys if k in report}

class InvestigatorTools:
    def __init__(self, journal: Journal) -> None:
        from . import environment as env
        self.env = env
        self.journal = journal
        self.candidate = dict(env.BASELINE)
        self.verified_digest: str | None = None
        self.validation: dict | None = None
        self.probed: set[str] = set()
        self.inspected = False
        self.context_loaded = False
        self.finished = False
        self.final_report: dict | None = None
        self.patch_count = 0
        self.tool_counts: dict[str, int] = {}

    def initial_evidence(self) -> dict:
        baseline = self.env.verify_candidate(self.env.BASELINE, seed=20261010, count=80)
        shortcut = self.env.verify_candidate(self.env.SHORTCUT, seed=20261010, count=80)
        example_only = self.env.run_probe(self.env.SHORTCUT, 'incident')
        self.journal.save('baseline.json', baseline)
        self.journal.save('incoming_shortcut.json', {'config': self.env.SHORTCUT,
            'single_incident': example_only, 'independent_verification': shortcut})
        data = {'incident': self.env.read_incident(), 'available_probes': self.env.probe_catalog(),
                'baseline': compact_verification(baseline),
                'incoming_patch': {'config': self.env.SHORTCUT,
                    'single_incident_passed': example_only['passed'],
                    'independent_verification': compact_verification(shortcut)},
                'note': 'The incoming quick fix is a declared synthetic fixture, not a fabricated model response.'}
        self.journal.emit('intake_and_shortcut_check', data)
        return data

    def dispatch(self, action: str, arguments: dict) -> dict:
        allowed = {'inspect_incident', 'inspect_code', 'probe', 'propose_patch', 'verify_candidate', 'finish'}
        if action not in allowed:
            return {'error': 'Unknown tool', 'allowed': sorted(allowed)}
        self.tool_counts[action] = self.tool_counts.get(action, 0) + 1
        if action == 'inspect_incident':
            self.inspected = True
            return self.env.read_incident()
        if action == 'inspect_code':
            query = arguments.get('query', 'refund policy cache retry payment idempotency')
            if not isinstance(query, str) or len(query) > 300:
                return {'error': 'query must be a short string'}
            binary = ROOT / '.tools' / 'entire-graph'
            if not binary.is_file():
                return {'error': 'Entire graph unavailable; no substitute evidence claimed'}
            result = subprocess.run([str(binary), 'search', '--repo', str(ROOT), '--query', query,
                '--format', 'json', '--top-k', '3', '--max-context-bytes', '6500'],
                capture_output=True, text=True, timeout=30)
            if result.returncode:
                return {'error': 'Entire search failed', 'exit_code': result.returncode,
                        'detail': result.stderr[-300:]}
            try:
                output = json.loads(result.stdout)
            except json.JSONDecodeError:
                output = {'text': result.stdout[:6500]}
            self.journal.save('entire_code_context.json', {'query': query, 'result': output,
                                                        'source': 'entire-graph'})
            self.context_loaded = True
            return {'source': 'Entire graph', 'result': output}
        if action == 'probe':
            probe_id = arguments.get('probe_id')
            ids = {x['id'] for x in self.env.probe_catalog()}
            if probe_id not in ids:
                return {'error': 'Unknown probe_id', 'allowed': sorted(ids)}
            self.probed.add(probe_id)
            return self.env.run_probe(self.candidate, probe_id)
        if action == 'propose_patch':
            if self.patch_count >= 4:
                return {'error': 'Patch budget exhausted; report unresolved incident'}
            candidate = self.env.validate_config(arguments.get('config', {}))
            old = dict(self.candidate)
            self.candidate = candidate
            self.verified_digest = None
            self.patch_count += 1
            patch = [{'op': 'replace', 'path': '/' + key, 'old': old[key], 'value': candidate[key]}
                     for key in sorted(candidate) if candidate[key] != old[key]]
            self.journal.save(f'candidate_{self.patch_count}.patch.json', patch)
            return {'candidate': candidate, 'patch': patch, 'candidate_sha256': self.env.config_digest(candidate),
                    'status': 'UNVERIFIED_CANDIDATE', 'production_modified': False}
        if action == 'verify_candidate':
            result = self.env.verify_candidate(self.candidate, seed=20261010, count=80)
            self.validation = result
            self.verified_digest = self.env.config_digest(self.candidate) if result['passed'] else None
            self.journal.save(f'verification_{self.patch_count}.json', result)
            return compact_verification(result)
        if not self.inspected or not self.probed or not self.context_loaded:
            return {'error': 'Read the incident, inspect repository context, and run a diagnostic probe before finishing.'}
        if self.verified_digest != self.env.config_digest(self.candidate):
            return {'error': 'No passing independent verification for this exact candidate.'}
        seed = secrets.randbelow(2**31)
        fresh = self.env.verify_candidate(self.candidate, seed=seed, count=128)
        self.journal.save('frozen_candidate_validation.json', {'seed': seed, 'config': self.candidate,
            'config_sha256': self.verified_digest, 'result': fresh})
        if not fresh['passed']:
            self.verified_digest = None
            return {'error': 'Frozen-candidate validation failed. Candidate is not releasable.',
                    'verification': compact_verification(fresh)}
        self.finished = True
        self.final_report = {'status': 'VALIDATED_SANDBOX_CANDIDATE', 'run_id': self.journal.run_id,
            'candidate': self.candidate, 'candidate_sha256': self.verified_digest,
            'regression': compact_verification(self.validation),
            'fresh_generated_validation': compact_verification(fresh),
            'fresh_validation_seed': seed, 'tool_counts': self.tool_counts,
            'production_modified': False, 'human_release_approval_required': True,
            'claim_boundary': 'Observed synthetic sandbox results, not a production safety guarantee.'}
        self.journal.save('report.json', self.final_report)
        return self.final_report

DECISION_SCHEMA = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'enum': ['inspect_incident', 'inspect_code', 'probe',
                                             'propose_patch', 'verify_candidate', 'finish']},
        'arguments': {'type': 'object', 'properties': {
            'query': {'type': 'string'}, 'probe_id': {'type': 'string'},
            'config': {'type': 'object', 'properties': {
                'policy_source': {'type': 'string', 'enum': ['cache', 'current', 'deny_all']},
                'idempotency_key': {'type': 'string', 'enum': ['attempt', 'business_operation']}
            }, 'required': ['policy_source', 'idempotency_key'], 'additionalProperties': False}
        }, 'additionalProperties': False},
        'decision_summary': {'type': 'string'}
    },
    'required': ['action', 'arguments', 'decision_summary'], 'additionalProperties': False
}
SYSTEM = '''You are NeatRescue, an incident-investigation and repair-validation agent.
Goal: fix the reported synthetic refund workflow without breaking valid customers or paying twice.
You choose tools, see real sandbox results, and choose the next action. Never invent results.
Return exactly one JSON tool decision with action, arguments, decision_summary.
The summary is a short public action justification, NOT hidden reasoning.
Tools:
inspect_incident {}: read business contract, incident, current configuration.
inspect_code {query}: inspect real repository context using Entire graph.
probe {probe_id}: run a diagnostic case on the current candidate. Catalog is supplied.
propose_patch {config:{policy_source, idempotency_key}}: change these two sandbox config fields only.
verify_candidate {}: independently test the candidate; failures are returned.
finish {}: produce a candidate release only after verification; the system also checks fresh cases.
Read incident and code and test an informative probe before patching. Do not merely stop all refunds.
A refund committed before its acknowledgement is lost must not be committed again on retry.
Changing a candidate invalidates earlier verification. No deployment or real payment tools exist.
There are at most 14 tool decisions. Repeated identical tools are rarely useful; use evidence to progress.
'''

def planning_context(engine: InvestigatorTools, initial: dict) -> tuple[dict, dict]:
    """Explicit durable progress and non-repeating tool availability, not a repair script."""
    allowed = []
    if not engine.inspected:
        allowed.append('inspect_incident')
    if not engine.context_loaded:
        allowed.append('inspect_code')
    remaining = [p['id'] for p in engine.env.probe_catalog() if p['id'] not in engine.probed]
    if remaining and len(engine.probed) < 3:
        allowed.append('probe')
    ready = engine.inspected and engine.context_loaded and bool(engine.probed)
    if ready:
        current_hash = engine.env.config_digest(engine.candidate)
        if engine.verified_digest == current_hash:
            allowed.append('finish')
        else:
            if engine.patch_count < 4:
                allowed.append('propose_patch')
            if engine.patch_count and (not engine.validation or engine.validation.get('config_sha256') != current_hash):
                allowed.append('verify_candidate')
    schema = copy.deepcopy(DECISION_SCHEMA)
    schema['properties']['action']['enum'] = allowed
    schema['properties']['arguments']['properties']['probe_id']['enum'] = remaining or ['none']
    observed = [e['data'] for e in engine.journal.events if e['kind'] == 'tool_result']
    state = {'goal': 'Repair policy and retry failures without denying legitimate refunds.',
             'incident': initial['incident'], 'candidate': engine.candidate,
             'incoming_patch_failed_regression': not initial['incoming_patch']['independent_verification']['passed'],
             'allowed_actions': allowed, 'available_probe_ids': remaining,
             'progress': {'incident_read':engine.inspected, 'code_context_read':engine.context_loaded,
                          'completed_probes':sorted(engine.probed), 'patch_count':engine.patch_count,
                          'candidate_verified':engine.verified_digest is not None},
             'recent_tool_results': observed[-4:],
             'instruction': 'Choose a new useful allowed action. Do not repeat a completed probe. Inspect required evidence, then propose and verify a patch.'}
    return state, schema

def run_live(model: str = 'qwen3:4b', max_steps: int = 14) -> dict:
    load_local_environment()
    import neatlogs
    key = os.environ.get('NEATLOGS_API_KEY', '').strip()
    if key.startswith('<'):
        key = ''
    neatlogs.init(api_key=key or None, endpoint='https://ingest.neatlogs.com',
                  workflow_name='validate-agent-repair', instrumentations=['ollama'],
                  disable_export=not bool(key), tags=['neatHack', 'synthetic-sandbox'])
    from ollama import Client
    client = Client(host='http://127.0.0.1:11434', timeout=60)
    journal = Journal()
    engine = InvestigatorTools(journal)
    journal.save('manifest.json', {'model': model, 'execution_mode': 'LIVE_LLM',
        'neatlogs_export': 'ENABLED_NOT_YET_CONFIRMED' if key else 'LOCAL_ONLY_MISSING_KEY',
        'max_steps': max_steps, 'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'target': 'synthetic_refund_workflow', 'model_decisions_scripted': False,
        'planner': 'LLM selects within progress- and verification-constrained tool availability'})
    started = time.monotonic()
    try:
        with neatlogs.trace('validate-agent-repair', kind='WORKFLOW'):
            traced_intake = neatlogs.span(kind='TOOL', tool_name='independent-intake-checks', capture_input=True, capture_output=True)(engine.initial_evidence)
            initial = traced_intake()
            messages = [{'role': 'system', 'content': SYSTEM},
                        {'role': 'user', 'content': canonical(initial)}]
            for step in range(max_steps):
                if time.monotonic() - started > 480:
                    raise TimeoutError('Bounded run time exhausted')
                state, decision_schema = planning_context(engine, initial)
                if not state['allowed_actions']:
                    raise RuntimeError('No remaining safe actions without progress')
                messages = [{'role':'system','content':SYSTEM}, {'role':'user','content':canonical(state)}]
                kwargs = {'model': model, 'messages': messages, 'format': decision_schema, 'stream': False,
                          'options': {'temperature': 0.2, 'seed': 4242, 'num_ctx': 8192, 'num_predict': 480},
                          'keep_alive': '1m'}
                if model.startswith('qwen3'):
                    kwargs['think'] = False
                response = client.chat(**kwargs)
                raw = response.message.content or ''
                journal.emit('model_response', {'step': step, 'content': raw,
                    'prompt_tokens': response.prompt_eval_count, 'completion_tokens': response.eval_count,
                    'model': response.model})
                messages.append({'role': 'assistant', 'content': raw})
                try:
                    decision = json.loads(raw)
                    action = decision['action']
                    arguments = decision['arguments']
                    if action not in state['allowed_actions']:
                        raise ValueError('Action not available in the current verified state')
                    if not isinstance(arguments, dict):
                        raise ValueError('arguments must be an object')
                    traced_dispatch = neatlogs.span(kind='TOOL', tool_name=action, capture_input=True, capture_output=True)(engine.dispatch)
                    result = traced_dispatch(action, arguments)
                    journal.emit('tool_result', {'action': action, 'arguments': arguments, 'result': result})
                except (ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
                    result = {'error': type(exc).__name__, 'message': str(exc)[:500]}
                    journal.emit('invalid_decision_or_tool_error', result)
                messages.append({'role': 'user', 'content': 'Tool result: ' + canonical(result)})
                if engine.finished:
                    journal.emit('terminal', {'status': engine.final_report['status'],
                                              'elapsed_s': round(time.monotonic() - started, 3)})
                    return engine.final_report
            raise RuntimeError('Action budget exhausted without a validated candidate')
    except Exception as exc:
        report = {'status': 'INCOMPLETE', 'run_id': journal.run_id,
                  'error': type(exc).__name__, 'detail': str(exc)[:600], 'candidate': engine.candidate,
                  'production_modified': False}
        journal.save('report.json', report)
        journal.emit('terminal', report)
        return report
    finally:
        flushed = neatlogs.flush(timeout_millis=5000)
        stopped = neatlogs.shutdown(timeout_millis=5000)
        journal.save('telemetry_status.json', {'export_key_present': bool(key),
            'flush_returned': bool(flushed), 'shutdown_returned': bool(stopped),
            'cloud_delivery_confirmed': False,
            'note': 'A successful local flush is not authenticated dashboard readback.'})

def main() -> int:
    parser = argparse.ArgumentParser(description='NeatRescue: bounded incident-investigation agent')
    parser.add_argument('--model', default=os.environ.get('NEATRESCUE_MODEL', 'qwen3:4b'))
    args = parser.parse_args()
    result = run_live(args.model)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'VALIDATED_SANDBOX_CANDIDATE' else 2

if __name__ == '__main__':
    raise SystemExit(main())
