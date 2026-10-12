"""Pure offline negative and crash/replay tests. No real model or payment calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from neatrescue import blind_agent, investigator, final_evaluation as gate, recover_verified
from tests.gate_fixtures import verified


class DurableFinalGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.mocks = [mock.patch.object(investigator, 'ROOT', self.root),
                      mock.patch.object(recover_verified, 'ROOT', self.root)]
        for m in self.mocks: m.start()
        self.stdout = contextlib.redirect_stdout(io.StringIO()); self.stdout.__enter__()
        self.journal = investigator.Journal('unit-final-origin')
        self.case = blind_agent.BlindCase(7719, self.journal)
        verified(self.case)
        self.origin = self.journal.directory
    def tearDown(self):
        self.stdout.__exit__(None, None, None)
        for m in self.mocks: m.stop()
        self.tmp.cleanup()
    def final(self):
        return gate.finalize(self.origin, self.case.current, 1, self.journal)
    def test_same_seed_and_verdict_on_repeated_call(self):
        with mock.patch.object(gate.secrets, 'randbelow', return_value=7711) as rng:
            first = self.final()
            with mock.patch.object(gate, 'evaluate_candidate', side_effect=AssertionError('must not re-execute')):
                second = self.final()
        self.assertEqual(rng.call_count, 1)
        self.assertEqual(first['plan'], second['plan'])
        self.assertEqual(first['outcome'], second['outcome'])
        self.assertTrue(second['reused_outcome'])
    def test_crash_after_plan_persistence_reuses_same_seed(self):
        actual = gate.evaluate_candidate
        def crash(source, seed, count):
            if count == 128: raise RuntimeError('injected crash before saving final result')
            return actual(source, seed, count)
        with mock.patch.object(gate.secrets, 'randbelow', return_value=8127) as rng:
            with mock.patch.object(gate, 'evaluate_candidate', side_effect=crash):
                with self.assertRaises(RuntimeError): self.final()
            plan = gate.read_json(self.origin/'final_plan.json')
            self.assertFalse((self.origin/'final_outcome.json').exists())
            final = self.final()
        self.assertEqual(rng.call_count, 1)
        self.assertEqual(plan, final['plan'])
        self.assertEqual(final['outcome']['seed'], 8127)
        attempts = gate.read_json(self.origin/'final_attempts.json')
        self.assertEqual([x['seed'] for x in attempts], [8127, 8127])
    def test_real_process_exit_preserves_plan_and_releases_lock(self):
        script = """import os,sys,json
from pathlib import Path
from neatrescue import investigator,final_evaluation as g
investigator.ROOT=Path(sys.argv[1])
j=investigator.Journal.resume('unit-final-origin')
source=g.read_json(j.directory/'patch_1.json')['source']
actual=g.evaluate_candidate
def crash(source,seed,count):
    if count==128:os._exit(86)
    return actual(source,seed,count)
g.evaluate_candidate=crash
g.finalize(j.directory,source,1,j)
"""
        p = subprocess.run([sys.executable, '-c', script, str(self.root)],
                           cwd=Path(gate.__file__).resolve().parents[1],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(p.returncode, 86, p.stderr)
        before = gate.read_json(self.origin/'final_plan.json')
        self.assertFalse((self.origin/'final_outcome.json').exists())
        with mock.patch.object(gate.secrets, 'randbelow', side_effect=AssertionError('redraw')):
            after = self.final()
        self.assertEqual(before, after['plan'])
        self.assertEqual(after['outcome']['status'], 'VALIDATED_SOURCE_PATCH')
        gate.verify_events(self.origin)

    def test_rejection_is_terminal_not_another_lottery(self):
        actual = gate.evaluate_candidate
        def failure(source, seed, count):
            result = actual(source, seed, count)
            if count == 128:
                result['passed'] = False
                result['injected_test_failure'] = True
            return result
        with mock.patch.object(gate, 'evaluate_candidate', side_effect=failure): first = self.final()
        self.assertEqual(first['outcome']['status'], 'REJECTED_FINAL_VALIDATION')
        with mock.patch.object(gate.secrets, 'randbelow', side_effect=AssertionError('seed redraw')):
            with mock.patch.object(gate, 'evaluate_candidate', side_effect=AssertionError('new attempt')):
                again = self.final()
        self.assertEqual(again['outcome'], first['outcome'])
    def test_concurrent_callers_share_one_plan(self):
        with mock.patch.object(gate.secrets, 'randbelow', return_value=71) as rng:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.final(), range(2)))
        self.assertEqual(rng.call_count, 1)
        self.assertEqual(results[0]['outcome'], results[1]['outcome'])
        self.assertEqual(sorted(r['reused_outcome'] for r in results), [False, True])
    def test_altered_patch_and_its_digest_do_not_match_model_record(self):
        source = self.case.current + '\n# changed\n'
        data = gate.read_json(self.origin/'patch_1.json')
        data.update(source=source, sha256=gate.sha(source))
        gate.atomic_json(self.origin/'patch_1.json', data)
        with self.assertRaises(ValueError): self.final()
    def test_verifier_version_mismatch_refuses_before_rng(self):
        identity = gate.verifier_identity(); identity['suite'] += '/altered'
        with mock.patch.object(gate, 'verifier_identity', return_value=identity):
            with mock.patch.object(gate.secrets, 'randbelow', side_effect=AssertionError('must not allocate')):
                with self.assertRaisesRegex(ValueError, 'version|binding'): self.final()
    def test_original_source_tampering_fails(self):
        data = gate.read_json(self.origin/'source_before.json')
        data['source'] += '\n# tampered\n'
        gate.atomic_json(self.origin/'source_before.json', data)
        with self.assertRaisesRegex(ValueError, 'Original source'): self.final()
    def test_missing_model_proposal_is_not_accepted(self):
        rows = gate.verify_events(self.origin)
        for row in rows:
            if row['kind'] == 'blind_model_decision': row['kind'] = 'not_a_model_proposal'
        previous = '0'*64
        for row in rows:
            row.pop('event_hash'); row['previous_hash'] = previous
            previous = gate.digest(row); row['event_hash'] = previous
        (self.origin/'events.jsonl').write_text(''.join(gate.canonical(x)+'\n' for x in rows))
        with self.assertRaisesRegex(ValueError, 'recorded model'): self.final()
    def test_legacy_unbound_results_are_refused(self):
        (self.origin/'development_1_binding.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Legacy/unbound'): self.final()
    def test_deleted_plan_after_interruption_does_not_allocate_new_seed(self):
        actual = gate.evaluate_candidate
        def crash(source, seed, count):
            if count == 128: raise RuntimeError('injected')
            return actual(source, seed, count)
        with mock.patch.object(gate, 'evaluate_candidate', side_effect=crash):
            with self.assertRaises(RuntimeError): self.final()
        (self.origin/'final_plan.json').unlink()
        with mock.patch.object(gate.secrets, 'randbelow', side_effect=AssertionError('redraw')):
            with self.assertRaisesRegex(ValueError, 'Missing plan'): self.final()

    def test_changed_plan_seed_is_detected_against_freeze_event(self):
        self.final()
        plan = gate.read_json(self.origin/'final_plan.json')
        plan['seed'] += 1; plan.pop('plan_sha256'); plan['plan_sha256'] = gate.digest(plan)
        gate.atomic_json(self.origin/'final_plan.json', plan)
        with self.assertRaisesRegex(ValueError, 'freeze identity'): self.final()
    def test_candidate_change_after_freeze_forbids_new_plan(self):
        first = self.final()
        self.case.current += '\n# changed source\n'
        with self.assertRaises(ValueError): self.final()
        self.assertEqual(first['plan'], gate.read_json(self.origin/'final_plan.json'))
    def test_end_to_end_recovery_twice_uses_origin_and_one_receipt(self):
        self.journal.save('report.json', {'status':'INCOMPLETE','error':'injected','run_id':self.journal.run_id})
        sealed_before = (self.origin/'sealed_incident.json').read_bytes()
        fake_sdk = types.SimpleNamespace(init=lambda **k:None, trace=lambda *a,**k:contextlib.nullcontext(),
            span=lambda **k:(lambda f:f), flush=lambda **k:True, shutdown=lambda **k:True)
        with mock.patch.dict(sys.modules, {'neatlogs':fake_sdk}):
            with mock.patch.object(gate.secrets, 'randbelow', return_value=99812) as rng:
                first = recover_verified.recover(self.journal.run_id)
                with mock.patch.object(gate, 'evaluate_candidate', side_effect=AssertionError('new validation')):
                    second = recover_verified.recover(self.journal.run_id)
        self.assertEqual(rng.call_count, 1)
        self.assertEqual(first['run_id'], second['run_id'])
        self.assertEqual(first['final_outcome_sha256'], second['final_outcome_sha256'])
        self.assertTrue(second['final_outcome_reused'])
        self.assertEqual(len(list((self.root/'runs').iterdir())), 1)
        self.assertEqual(sealed_before, (self.origin/'sealed_incident.json').read_bytes())
        self.assertEqual(gate.read_json(self.origin/'report_before_recovery.json')['status'], 'INCOMPLETE')
        gate.verify_events(self.origin)

if __name__ == '__main__': unittest.main()
