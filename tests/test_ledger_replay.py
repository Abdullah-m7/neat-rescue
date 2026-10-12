"""Offline tests for the real-SQLite ledger replay.

reference_source is private benchmark state, used here only as an offline
fixture. Each test runs one deterministic synthetic scenario on a fresh
temporary database: nothing here measures production reliability or safety.
"""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from neatrescue import blindbench as b
from neatrescue import ledger_replay as lr

def patched(name, source):
    tree = ast.parse(b.reference_source())
    new = ast.parse(source).body[0]
    tree.body = [new if isinstance(n, ast.FunctionDef) and n.name == name else n for n in tree.body]
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'

ATTEMPT_IN_KEY = patched('operation_key', "def operation_key(event):\n"
                         "    return event['tenant_id'] + '/' + event['refund_id'] + '/' + event['attempt_id']\n")
ORDER_ONLY = patched('operation_key', "def operation_key(event):\n    return 'order#' + event['order_id']\n")
DENY_ALL = patched('eligible', "def eligible(order, policy):\n    return False\n")

def kinds(report):
    return [event['kind'] for event in report['events']]

def amounts(report, role):
    lid = next(op for op in report['scenario']['operations'] if op['role'] == role)
    key = '{0}|{1}'.format(lid['tenant_id'], lid['refund_id'])
    return report['expected']['logical_operations'][key], report['observed']['logical_operations'].get(key)

class LedgerReplayTests(unittest.TestCase):
    def test_correct_source_passes_on_two_seeds(self):
        for seed in (117, 20261010):
            report = lr.replay(b.reference_source(), seed=seed)
            self.assertTrue(report['passed'], report['differences'])
            self.assertTrue(report['retry_only_passed'])
            self.assertEqual(report['errors'], [])
            self.assertEqual(report['protocol'], 'ledger-replay/v1')
            self.assertTrue(report['synthetic'] and report['no_production_changes'])
            self.assertEqual(sorted(report['invariants']), sorted(lr.INVARIANT_NAMES))
            self.assertTrue(all(report['invariants'].values()))
            for kind in ('COMMIT', 'ACK_LOST', 'CONNECTION_CLOSED', 'REOPEN', 'REPLAY', 'NEW_PAYMENT'):
                self.assertIn(kind, kinds(report))
            self.assertNotIn('DUPLICATE_PAYMENT', kinds(report))
            want, got = amounts(report, 'base')
            self.assertEqual(got['payments'], 1)
            self.assertEqual(got['amount_cents'], want['amount_cents'])
            self.assertGreaterEqual(want['amount_cents'], 12900)
            self.assertEqual(len(report['observed']['payment_rows']), 3)

    def test_attempt_id_in_key_pays_the_same_refund_twice(self):
        report = lr.replay(ATTEMPT_IN_KEY, seed=117)
        self.assertFalse(report['passed'])
        self.assertFalse(report['retry_only_passed'])
        self.assertFalse(report['invariants']['no_duplicate_payment_after_retry'])
        self.assertIn('DUPLICATE_PAYMENT', kinds(report))
        self.assertTrue(report['differences']['duplicate_operations'])
        want, got = amounts(report, 'base')
        self.assertEqual(got['payments'], 2)
        self.assertEqual(got['amount_cents'], 2 * want['amount_cents'])
        self.assertFalse(report['invariants']['inventory_correct'])

    def test_order_only_key_passes_retry_only_but_loses_siblings(self):
        report = lr.replay(ORDER_ONLY, seed=117)
        self.assertTrue(report['retry_only_passed'])
        self.assertTrue(report['invariants']['no_duplicate_payment_after_retry'])
        self.assertFalse(report['passed'])
        self.assertFalse(report['invariants']['legitimate_sibling_paid'])
        self.assertFalse(report['invariants']['other_tenant_paid'])
        self.assertEqual(kinds(report).count('BLOCKED'), 2)
        for role in ('sibling', 'other_tenant'):
            self.assertIsNone(amounts(report, role)[1])
        self.assertEqual(len(report['observed']['payment_rows']), 1)

    def test_deny_all_eligibility_fails_everything(self):
        report = lr.replay(DENY_ALL, seed=117)
        self.assertFalse(report['passed'])
        self.assertFalse(report['retry_only_passed'])
        self.assertEqual(len(report['differences']['missed_operations']), 3)
        self.assertEqual(kinds(report).count('REJECTED'), 4)
        self.assertFalse(report['invariants']['commit_survived_connection_restart'])
        self.assertEqual(report['observed']['payment_rows'], [])

    def test_reopen_reads_rows_back_from_the_closed_connection(self):
        report = lr.replay(b.reference_source(), seed=117)
        commit = next(e for e in report['events'] if e['kind'] == 'COMMIT')
        reopen = next(e for e in report['events'] if e['kind'] == 'REOPEN')
        self.assertEqual(reopen['data']['mechanism'], 'connection restart')
        self.assertEqual(reopen['data']['connection_generation'], 2)
        self.assertEqual(reopen['data']['rows_read_back'],
                         [{'operation_key': commit['data']['operation_key'],
                           'attempt_id': commit['data']['attempt_id'],
                           'amount_cents': commit['data']['amount_cents']}])
        self.assertNotEqual(reopen['data']['retry_attempt_id'], commit['data']['attempt_id'])
        self.assertNotEqual(len(reopen['data']['retry_attempt_id']), len(commit['data']['attempt_id']))
        self.assertTrue(report['invariants']['commit_survived_connection_restart'])
        first_order = report['scenario']['orders'][0]
        slot = '{0}|{1}'.format(first_order['tenant_id'], first_order['order_id'])
        self.assertEqual(reopen['data']['stock_read_back'][slot], first_order['stock'] - 2)

    def test_supplied_database_is_created_once_and_kept(self):
        with tempfile.TemporaryDirectory() as room:
            path = Path(room) / 'ledger.sqlite3'
            report = lr.replay(b.reference_source(), seed=117, database_path=path)
            self.assertTrue(report['passed'])
            self.assertFalse(report['database_temporary'])
            conn = sqlite3.connect(str(path))
            try:
                schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='payments'").fetchone()[0]
                self.assertIn('UNIQUE', schema)
                self.assertEqual(conn.execute('SELECT count(*) FROM payments').fetchone()[0], 3)
            finally:
                conn.close()
            with self.assertRaises(ValueError):
                lr.replay(b.reference_source(), seed=117, database_path=path)

    def test_default_database_is_temporary_and_removed(self):
        report = lr.replay(b.reference_source(), seed=117)
        self.assertTrue(report['database_temporary'])
        self.assertFalse(Path(report['database_path']).exists())

    def test_reports_repeat_exactly_apart_from_the_local_path(self):
        first, second = (lr.replay(b.reference_source(), seed=117) for _ in range(2))
        third = lr.replay(b.reference_source(), seed=118)
        for report in (first, second, third):
            report.pop('database_path')
        self.assertEqual(first, second)
        self.assertEqual(first['scenario_sha256'], second['scenario_sha256'])
        self.assertNotEqual(first['scenario_sha256'], third['scenario_sha256'])
        self.assertEqual(first['source_sha256'], third['source_sha256'])

    def test_unsupported_source_is_rejected_before_any_file_appears(self):
        with tempfile.TemporaryDirectory() as room:
            path = Path(room) / 'never.sqlite3'
            for source in ('import os\n', 'def eligible(order, policy):\n    return True\n', ''):
                with self.assertRaises(ValueError):
                    lr.replay(source, seed=117, database_path=path)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(room).iterdir()), [])

    def test_seed_must_be_a_real_int(self):
        for seed in (True, 1.5, '117', None):
            with self.assertRaises(ValueError):
                lr.replay(b.reference_source(), seed=seed)

if __name__ == '__main__':
    unittest.main()
