"""Offline tests for the blind source-repair benchmark."""

import inspect
import unittest

from neatrescue import blindbench as bb

STDLIB_IMPORTS = {"ast", "hashlib", "json", "random", "copy"}
DENY_ALL = "def eligible(order, policy):\n    return False"
CURRENT_POLICY_ONLY = bb._variant("eligible", "ok")


def swap(source, definition):
    """Replace one function definition in a composed source."""
    header = next("def " + n + "(" for n in bb.FUNCTION_NAMES if "def " + n + "(" in definition)
    chunks = source.split("\n\n")
    if not any(chunk.lstrip().startswith(header) for chunk in chunks):
        raise AssertionError("no definition to replace: " + header)
    out = [definition.rstrip("\n") if c.lstrip().startswith(header) else c for c in chunks]
    return "\n\n".join(out).rstrip("\n") + "\n"


def multi_fault_seed(family="eligibility"):
    for seed in range(200):
        incident = bb.make_incident(seed)
        families = [mid.split("/")[0] for mid in incident["mutation_ids"]]
        if family in families and len(families) >= 2:
            return seed, incident
    raise AssertionError("no multi-fault incident found")


class ReferenceSourceTest(unittest.TestCase):
    def test_reference_passes_several_seeds(self):
        source = bb.reference_source()
        bb.validate_source(source)
        for seed in (1, 2, 1337):
            result = bb.evaluate(source, seed)
            self.assertTrue(result["passed"], result["first_failures"])
            self.assertEqual((result["passes"], result["failures"]), (result["total"], 0))

    def test_every_family_represented_and_probe_filter(self):
        source = bb.reference_source()
        full = bb.evaluate(source, 5, 16)
        self.assertEqual(sorted(full["by_family"]), sorted(bb.PROBES))
        self.assertEqual([t["total"] for t in full["by_family"].values()], [4, 4, 4, 4])
        single = bb.evaluate(source, 5, 16, probe="tenant_retry")
        self.assertEqual(list(single["by_family"]), ["tenant_retry"])
        self.assertEqual(single["total"], 16)

    def test_cases_vary_by_seed_and_hashes_are_stable(self):
        source = bb.reference_source()
        digests = {bb.evaluate(source, seed)["cases_sha256"] for seed in (1, 2, 3, 4)}
        self.assertEqual(len(digests), 4)
        first = bb.evaluate(source, 9, 32)
        self.assertEqual(first, bb.evaluate(source, 9, 32))
        self.assertNotEqual(first["cases_sha256"], bb.evaluate(source, 9, 64)["cases_sha256"])
        self.assertEqual(first["source_sha256"], bb.evaluate(source, 11, 32)["source_sha256"])


class IncidentTest(unittest.TestCase):
    def test_public_shape_and_hidden_diagnosis(self):
        one, two = bb.make_incident(3), bb.make_incident(44)
        self.assertEqual(one["contract"], two["contract"])
        self.assertNotEqual(one["incident_id"], two["incident_id"])
        for incident in (one, two):
            self.assertEqual(set(incident), set(bb.PUBLIC_INCIDENT_KEYS) | {"mutation_ids"})
            self.assertGreaterEqual(len(incident["mutation_ids"]), 2)
            public = repr([incident[key] for key in bb.PUBLIC_INCIDENT_KEYS])
            for mutation_id in incident["mutation_ids"]:
                self.assertNotIn(mutation_id, public)
                self.assertNotIn(mutation_id.split("/")[1], public)
            self.assertNotIn(bb.reference_source(), public)
            self.assertNotIn("#", incident["faulty_source"])

    def test_seeded_faults_fail_exactly_their_families(self):
        for seed in range(12):
            incident = bb.make_incident(seed)
            bb.validate_source(incident["faulty_source"])
            result = bb.evaluate(incident["faulty_source"], seed, 16)
            failing = {name for name, tally in result["by_family"].items() if tally["failures"]}
            self.assertFalse(result["passed"])
            self.assertGreaterEqual(len(failing), 2)
            self.assertEqual(failing, {mid.split("/")[0] for mid in incident["mutation_ids"]})
            self.assertLessEqual(len(result["first_failures"]), 3)
            for failure in result["first_failures"]:
                self.assertEqual(set(failure), {"case_id", "family", "input", "expected", "observed"})

    def test_deny_all_shortcut_passes_smoke_but_fails_evaluation(self):
        source = swap(bb.reference_source(), DENY_ALL)
        self.assertTrue(bb.smoke_example(source)["passed"])
        result = bb.evaluate(source, 6)
        self.assertFalse(result["passed"])
        self.assertTrue(result["by_family"]["eligibility"]["failures"])

    def test_current_policy_only_repair_is_insufficient(self):
        seed, incident = multi_fault_seed()
        partial = swap(incident["faulty_source"], CURRENT_POLICY_ONLY)
        self.assertNotEqual(partial, incident["faulty_source"])
        result = bb.evaluate(partial, seed)
        self.assertFalse(result["passed"])
        self.assertEqual(result["by_family"]["eligibility"]["failures"], 0)
        self.assertTrue(bb.evaluate(bb.reference_source(), seed)["passed"])


class ValidationTest(unittest.TestCase):
    def test_rejects_unsupported_constructs(self):
        cases = {
            "import": "import os\n\n\ndef eligible(order, policy):\n    return False",
            "builtins_escape": "def eligible(order, policy):\n    return open('x')",
            "dunder": "def eligible(order, policy):\n    return order.__class__",
            "getattr": "def eligible(order, policy):\n    return getattr(order, 'x')",
            "recursion": "def eligible(order, policy):\n    return eligible(order, policy)",
            "loop": "def eligible(order, policy):\n    while True:\n        return False",
            "comprehension": "def eligible(order, policy):\n    return [x for x in order]",
            "power": "def eligible(order, policy):\n    return order['age_days'] ** 2 > 0",
            "multiply": "def eligible(order, policy):\n    return order['age_days'] * 2 > 0",
            "huge_literal": "def eligible(order, policy):\n    return order['age_days'] < 99999999999",
            "float": "def eligible(order, policy):\n    return order['age_days'] < 1.5",
            "long_string": "def operation_key(event):\n    return '" + "z" * 90 + "'",
            "bad_param_names": "def eligible(ord, pol):\n    return False",
            "extra_param": "def eligible(order, policy, extra):\n    return False",
            "default": "def eligible(order, policy=None):\n    return False",
            "annotation": "def eligible(order, policy) -> bool:\n    return False",
            "kwonly": "def eligible(order, *, policy):\n    return False",
            "decorator": "@staticmethod\ndef eligible(order, policy):\n    return False",
            "underscore_local": "def eligible(order, policy):\n    _tmp = 1\n    return False",
            "builtin_rebind": "def eligible(order, policy):\n    len = 1\n    return False",
            "global_name": "def eligible(order, policy):\n    return LIMIT > 0",
            "global_stmt": "def eligible(order, policy):\n    global x\n    return False",
            "print": "def eligible(order, policy):\n    print(order)\n    return False",
            "lambda": "def eligible(order, policy):\n    return (lambda: False)()",
            "class": "class K:\n    pass\n\n\ndef eligible(order, policy):\n    return False",
            "nested_def": "def eligible(order, policy):\n    def inner():\n        return False\n    return False",
            "get_on_local": "def eligible(order, policy):\n    local = order\n    return local.get('age_days') > 0",
            "slice": "def operation_key(event):\n    return event['refund_id'][0:2]",
            "augassign": "def eligible(order, policy):\n    age = 1\n    age += 1\n    return False",
        }
        for label, definition in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                bb.validate_source(swap(bb.reference_source(), definition))

    def test_rejects_structural_problems(self):
        reference = bb.reference_source()
        nested = "def eligible(order, policy):\n" + "".join(
            "    " * (i + 1) + "if order['age_days'] > 0:\n" for i in range(22)
        ) + "    " * 23 + "return False"
        cases = {
            "not_a_string": 42,
            "syntax_error": "def eligible(order, policy)\n    return False",
            "missing_function": CURRENT_POLICY_ONLY,
            "duplicate_function": reference + "\n" + CURRENT_POLICY_ONLY,
            "unexpected_function": reference + "\ndef helper(order):\n    return 1\n",
            "top_level_code": reference + "\nx = 1\n",
            "too_long": "def eligible(order, policy):\n    return False\n" + "\n" * 7000,
            "deep_nesting": nested,
            "too_many_assignments": "def eligible(order, policy):\n"
            + "".join("    v{0} = 1\n".format(i) for i in range(9)) + "    return False",
        }
        for label, source in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                bb.validate_source(source)

    def test_allows_get_on_parameter(self):
        bb.validate_source(swap(
            bb.reference_source(),
            "def eligible(order, policy):\n    return policy.get('window_days', 0) > 0",
        ))

    def test_nothing_executes_before_validation(self):
        with self.assertRaises(ValueError):
            bb.evaluate("raise SystemExit(1)\n", 1)
        with self.assertRaises(ValueError):
            bb.smoke_example(bb.reference_source() + "\nimport os\n")

    def test_runtime_errors_and_wrong_types_count_as_failures(self):
        broken = swap(bb.reference_source(), "def refund_cents(order):\n    return order['missing']")
        result = bb.evaluate(broken, 4, 16, probe="partial_refund")
        self.assertEqual(result["passes"], 0)
        self.assertTrue(result["first_failures"][0]["observed"].startswith("error: "))
        stringly = swap(
            bb.reference_source(),
            "def inventory_after(stock, qty, already_applied):\n    return str(stock)",
        )
        self.assertEqual(bb.evaluate(stringly, 4, 16, probe="inventory_replay")["failures"], 16)


class InputValidationTest(unittest.TestCase):
    def test_rejects_bad_seed_count_and_probe(self):
        source = bb.reference_source()
        for seed in (True, "1", 2.0, 2**40, None):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                bb.evaluate(source, seed)
        for count in (17, 8, 12, 516, 1024, True, 32.0, "32"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                bb.evaluate(source, 1, count)
        with self.assertRaises(ValueError):
            bb.evaluate(source, 1, 16, probe="nope")
        with self.assertRaises(ValueError):
            bb.make_incident(True)


class BoundaryTest(unittest.TestCase):
    def test_module_has_no_legacy_configuration(self):
        source = inspect.getsource(bb)
        imported = {
            line.split()[1].split(".")[0]
            for line in source.splitlines()
            if line.startswith(("import ", "from "))
        }
        self.assertLessEqual(imported, STDLIB_IMPORTS)
        for token in ("neatrescue.", "environment", "CONFIG", "VARIANT", "variant_a"):
            self.assertNotIn(token, source)

    def test_reference_oracle_is_not_reachable_from_incidents(self):
        reference = bb.reference_source()
        self.assertNotIn(reference, repr(bb.make_incident(21)))
        self.assertEqual(reference, bb.reference_source())


if __name__ == "__main__":
    unittest.main()
