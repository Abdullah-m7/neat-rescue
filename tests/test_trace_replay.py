"""Offline contract checks for the Neatlogs real-program replay.

These tests never contact Neatlogs or any model.
"""
import unittest

from neatrescue.trace_replay import CASE_FILES, _evaluate


class CloudReplayEvidenceTests(unittest.TestCase):
    def test_recorded_candidate_paths_match_the_synthetic_ledger(self):
        for label, file_name, rows, correct in CASE_FILES:
            with self.subTest(candidate=label):
                report = _evaluate(label, file_name, 117)
                self.assertEqual(report["payment_rows"], rows)
                self.assertIs(report["passed"], correct)
                self.assertEqual(report["total_invariants"], 8)
                self.assertTrue(report["committed_row_read_after_reopen"])
                self.assertTrue(report["synthetic"])
                self.assertTrue(report["no_production_changes"])

    def test_accepted_candidate_all_eight_invariants(self):
        report = _evaluate("verified", "accepted_source.py", 117)
        self.assertEqual(report["passed_invariants"], 8)


if __name__ == "__main__":
    unittest.main()
