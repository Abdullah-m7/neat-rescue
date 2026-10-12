"""Controller boundaries tested offline. Not autonomous repair evidence."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from neatrescue import blind_agent as b
from neatrescue import blindbench as bench
from neatrescue import investigator as inv
from tests.gate_fixtures import prepare, record

class BlindGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=mock.patch.object(inv,'ROOT',Path(self.tmp.name));self.root.start()
        self.journal=inv.Journal('unit-blind-case')
        self.case=b.BlindCase(7719,self.journal)
    def tearDown(self):
        self.root.stop();self.tmp.cleanup()
    def do(self, decision):
        return record(self.case, decision)

    def prepare(self):
        prepare(self.case)
    def test_public_view_excludes_private_manifest(self):
        view=self.case.planner_view()
        self.assertNotIn('faulty_source',view['incident'])
        self.assertNotIn('private',view['incident'])
        self.assertNotIn('mutation_ids',json.dumps(view))
        self.assertFalse((self.case.workspace/'sealed_incident.json').exists())
        self.assertTrue((self.journal.directory/'sealed_incident.json').exists())
        self.assertEqual(view['current_source'],'Use inspect_source')
    def test_cannot_submit_without_diagnostics(self):
        with self.assertRaises(ValueError):
            self.do({'action':'submit_patch','source':bench.reference_source()})
    def test_reject_unsafe_source_before_writing(self):
        self.prepare();before=(self.case.workspace/'adapter.py').read_text()
        with self.assertRaises(ValueError):
            self.do({'action':'submit_patch','source':'import os\n'+bench.reference_source()})
        self.assertEqual((self.case.workspace/'adapter.py').read_text(),before)
    def test_pending_candidate_must_be_tested(self):
        self.prepare();self.do({'action':'submit_patch','source':bench.reference_source()})
        self.assertEqual(self.case.actions(),['test_patch'])
        with self.assertRaises(ValueError):
            self.do({'action':'submit_patch','source':bench.reference_source()})
        self.assertEqual(self.case.patch_count,1)
    def test_noop_patch_not_progress(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.do({'action':'submit_patch','source':self.case.current})
        self.assertEqual(self.case.patch_count,0)
    def test_frozen_candidate_checked_with_new_seed(self):
        self.prepare();self.do({'action':'submit_patch','source':bench.reference_source()})
        self.assertTrue(self.do({'action':'test_patch'})['passed'])
        self.assertEqual(self.case.actions(),['finish'])
        with mock.patch.object(b.secrets,'randbelow',return_value=432109):
            with contextlib.redirect_stdout(io.StringIO()):result=self.do({'action':'finish'})
        self.assertEqual(result['status'],'VALIDATED_SOURCE_PATCH')
        self.assertEqual(result['fresh_generated']['total'],128)
        self.assertEqual(result['fresh_seed'],432109)
        self.assertNotEqual(result['development']['cases_sha256'],result['fresh_generated']['cases_sha256'])
        self.assertFalse(result['production_modified'])
    def test_source_tampering_revokes_test_status(self):
        self.prepare();self.do({'action':'submit_patch','source':bench.reference_source()})
        self.do({'action':'test_patch'})
        self.case.current+='\n# new candidate bytes\n'
        self.assertEqual(self.case.actions(),['test_patch'])
        with self.assertRaises(ValueError):self.do({'action':'finish'})
    def test_incoming_fixture_cannot_be_accepted_on_smoke_only(self):
        result=self.do({'action':'challenge_incoming'})
        self.assertTrue(result['single_incident']['passed'])
        self.assertFalse(result['independent_validation']['passed'])
        self.assertTrue(self.case.challenged)
    def test_provider_error_is_not_a_decision(self):
        with self.assertRaises(RuntimeError):b.parse_planner_response({'is_error':True,'result':'usage limit'})
    def test_structured_response_parser(self):
        value={'action':'probe','probe':'eligibility','source':'','public_summary':'inspect'}
        self.assertEqual(b.parse_planner_response({'structured_output':value}),value)

if __name__=='__main__':unittest.main()
