"""Regression tests for false acceptances found by the Astra review.

Each defect passed both the previous 80-case development set and 128 fresh
cases. These tests cover missing semantic conditions, not more RNG samples.
"""
import ast
import unittest
from neatrescue import blindbench as b


def replacement(name, source):
    tree=ast.parse(b.reference_source())
    new=ast.parse(source).body[0]
    tree.body=[new if isinstance(n,ast.FunctionDef) and n.name==name else n for n in tree.body]
    return ast.unparse(ast.fix_missing_locations(tree))+'\n'


class ReviewCounterexampleTests(unittest.TestCase):
    def test_zero_and_one_are_explicitly_covered(self):
        cases=b._build_cases(11,80,None)
        ages={c['input']['order']['age_days'] for c in cases if c['family']=='eligibility'}
        self.assertTrue({0,1}.issubset(ages))
    def test_wrong_lower_age_limit_is_rejected(self):
        source=replacement('eligible',"def eligible(order, policy):\n    return 2 <= order['age_days'] <= policy['window_days']\n")
        for seed,count in ((20261010,80),(770171702,128),(1,80)):
            report=b.evaluate(source,seed=seed,count=count)
            self.assertFalse(report['passed'])
            self.assertGreater(report['by_family']['eligibility']['failures'],0)
    def test_equal_and_unequal_attempt_lengths_are_covered(self):
        cases=b._build_cases(11,80,None)
        equalities=[]
        for c in cases:
            if c['family']=='tenant_retry':
                base=c['input']['base']['attempt_id'];retry=c['input']['retry']['attempt_id']
                self.assertNotEqual(base,retry)
                equalities.append(len(base)==len(retry))
        self.assertIn(True,equalities);self.assertIn(False,equalities)
    def test_attempt_length_cannot_be_part_of_logical_key(self):
        source=replacement('operation_key',"def operation_key(event):\n    return event['tenant_id'] + ':' + event['refund_id'] + ':' + str(len(event['attempt_id']))\n")
        for seed,count in ((20261010,80),(770171702,128),(1,80)):
            report=b.evaluate(source,seed=seed,count=count)
            self.assertFalse(report['passed'])
            self.assertGreater(report['by_family']['tenant_retry']['failures'],0)
    def test_reference_remains_valid_and_protocol_is_versioned(self):
        for seed in (20261010,770171702,77):
            report=b.evaluate(b.reference_source(),seed=seed,count=128)
            self.assertTrue(report['passed'])
            self.assertEqual(report['evaluation_protocol'],'blindbench/2.1-boundary-and-retry-coverage')

if __name__=='__main__':unittest.main()
