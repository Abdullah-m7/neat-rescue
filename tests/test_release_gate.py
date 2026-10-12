"""Offline verifier-gate tests; these are not live-agent execution evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from neatrescue import investigator as inv
from neatrescue import environment as env

GOOD = {'policy_source': 'current', 'idempotency_key': 'business_operation'}

class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root_patch = mock.patch.object(inv, 'ROOT', Path(self.temp.name))
        self.root_patch.start()
        self.journal = inv.Journal('offline-gate-test')
        self.engine = inv.InvestigatorTools(self.journal)
    def tearDown(self):
        self.root_patch.stop(); self.temp.cleanup()
    def test_unverified_finish_rejected(self):
        self.assertIn('error', self.engine.dispatch('finish', {}))
        self.assertFalse(self.engine.finished)
    def test_unknown_tool_rejected(self):
        self.assertIn('error', self.engine.dispatch('deploy_to_production', {}))
    def test_shortcut_fools_one_example_not_validator(self):
        self.assertTrue(env.run_probe(env.SHORTCUT, 'incident')['passed'])
        self.assertFalse(env.run_probe(env.SHORTCUT, 'recent_order')['passed'])
        self.engine.dispatch('propose_patch', {'config': env.SHORTCUT})
        self.assertFalse(self.engine.dispatch('verify_candidate', {})['passed'])
        self.assertIsNone(self.engine.verified_digest)
    def test_policy_only_fix_misses_duplicate_side_effect(self):
        self.engine.dispatch('propose_patch', {'config': {'policy_source':'current','idempotency_key':'attempt'}})
        result=self.engine.dispatch('probe', {'probe_id':'lost_ack_retry'})
        self.assertFalse(result['passed']); self.assertGreater(result['duplicate_payments'],0)
    def test_patch_change_invalidates_verified_candidate(self):
        self.engine.dispatch('propose_patch', {'config': GOOD})
        self.assertTrue(self.engine.dispatch('verify_candidate', {})['passed'])
        self.assertEqual(self.engine.verified_digest,env.config_digest(GOOD))
        self.engine.dispatch('propose_patch', {'config': env.BASELINE})
        self.assertIsNone(self.engine.verified_digest)
        self.assertIn('error',self.engine.dispatch('finish', {}))
    def test_invalid_patch_cannot_mutate(self):
        old=dict(self.engine.candidate)
        with self.assertRaises(ValueError):
            self.engine.dispatch('propose_patch', {'config': {'policy_source':'current','idempotency_key':'business_operation','shell':'unsafe'}})
        self.assertEqual(old,self.engine.candidate)
    def test_missing_entire_context_cannot_count_as_success(self):
        self.engine.dispatch('inspect_incident', {})
        self.engine.dispatch('probe', {'probe_id':'incident'})
        self.assertIn('error',self.engine.dispatch('inspect_code', {}))
        self.engine.dispatch('propose_patch', {'config': GOOD})
        self.engine.dispatch('verify_candidate', {})
        self.assertIn('error',self.engine.dispatch('finish', {}))
    def test_success_is_candidate_not_deployment(self):
        self.engine.inspected=True; self.engine.context_loaded=True
        self.engine.probed.add('incident')
        self.engine.dispatch('propose_patch', {'config': GOOD})
        self.engine.dispatch('verify_candidate', {})
        result=self.engine.dispatch('finish', {})
        self.assertEqual('VALIDATED_SANDBOX_CANDIDATE',result['status'])
        self.assertEqual(128,result['fresh_generated_validation']['total'])
        self.assertFalse(result['production_modified'])
        self.assertTrue(result['human_release_approval_required'])
    def test_append_only_event_chain(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.journal.emit('example', {'n':1});self.journal.emit('example', {'n':2})
        rows=[json.loads(s) for s in (self.journal.directory/'events.jsonl').read_text().splitlines()]
        previous='0'*64
        for row in rows:
            stored=row.pop('event_hash')
            self.assertEqual(previous,row['previous_hash']);self.assertEqual(stored,inv.digest(row));previous=stored
    def test_new_journal_cannot_overwrite_existing_run(self):
        with self.assertRaises(FileExistsError):inv.Journal('offline-gate-test')

if __name__=='__main__':unittest.main()
