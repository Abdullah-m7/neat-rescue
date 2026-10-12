"""Tests for the bounded refund sandbox in ``neatrescue.environment``.

These tests check that the sandbox states the problem honestly: the baseline
configuration must fail, the incoming quick fix must pass the single reported
example while failing an independent suite, and only a configuration that reads
the authoritative policy and keys payments by business operation may pass.

A green run here says the synthetic sandbox behaves as specified over the
generated scenarios. It is not evidence of production safety.
"""
import json
import unittest

from neatrescue import environment as env

HALF_FIX = {"policy_source": "current", "idempotency_key": "attempt"}
REPAIR = {"policy_source": "current", "idempotency_key": "business_operation"}


class ConfigValidationTests(unittest.TestCase):
    def test_declared_fixtures_are_valid_configs(self):
        self.assertEqual(env.validate_config(env.BASELINE), env.BASELINE)
        self.assertEqual(env.validate_config(env.SHORTCUT), env.SHORTCUT)
        self.assertNotEqual(env.BASELINE, env.SHORTCUT)

    def test_every_declared_combination_is_accepted(self):
        seen = set()
        for source in env.POLICY_SOURCES:
            for key in env.IDEMPOTENCY_KEYS:
                config = {"policy_source": source, "idempotency_key": key}
                normalized = env.validate_config(config)
                self.assertEqual(normalized, config)
                seen.add(env.config_digest(config))
        self.assertEqual(len(seen), len(env.POLICY_SOURCES) * len(env.IDEMPOTENCY_KEYS))

    def test_returns_an_independent_copy(self):
        source = dict(env.BASELINE)
        normalized = env.validate_config(source)
        normalized["policy_source"] = "current"
        self.assertEqual(source, env.BASELINE)
        self.assertEqual(env.BASELINE["policy_source"], "cache")

    def test_rejects_unknown_and_missing_keys(self):
        rejected = [
            {},
            {"policy_source": "current"},
            {"idempotency_key": "attempt"},
            dict(REPAIR, retries=3),
            dict(REPAIR, POLICY_SOURCE="current"),
            {"policy_source": "current", "idempotency_keys": "attempt"},
            {"policy_source": "current", "idempotency_key": "attempt", 7: "x"},
        ]
        for config in rejected:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    env.validate_config(config)

    def test_rejects_values_outside_the_closed_sets(self):
        rejected = [
            {"policy_source": "snapshot", "idempotency_key": "attempt"},
            {"policy_source": "current", "idempotency_key": "order"},
            {"policy_source": "Current", "idempotency_key": "attempt"},
            {"policy_source": " current", "idempotency_key": "attempt"},
            {"policy_source": None, "idempotency_key": "attempt"},
            {"policy_source": "current", "idempotency_key": True},
            {"policy_source": ["current"], "idempotency_key": "attempt"},
        ]
        for config in rejected:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    env.validate_config(config)

    def test_rejects_non_mapping_configs(self):
        for config in (None, "current", 3, ["current", "attempt"], ("a", "b")):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    env.validate_config(config)


class ConfigDigestTests(unittest.TestCase):
    def test_digest_is_stable_and_order_independent(self):
        first = env.config_digest({"policy_source": "current",
                                   "idempotency_key": "business_operation"})
        second = env.config_digest({"idempotency_key": "business_operation",
                                    "policy_source": "current"})
        self.assertEqual(first, second)
        self.assertEqual(first, env.config_digest(REPAIR))
        self.assertEqual(len(first), 64)
        self.assertTrue(all(char in "0123456789abcdef" for char in first))

    def test_digest_separates_distinct_configs(self):
        self.assertNotEqual(env.config_digest(REPAIR), env.config_digest(HALF_FIX))
        self.assertNotEqual(env.config_digest(env.BASELINE),
                            env.config_digest(env.SHORTCUT))

    def test_digest_rejects_invalid_config(self):
        with self.assertRaises(ValueError):
            env.config_digest({"policy_source": "current"})


class ScenarioBuildingTests(unittest.TestCase):
    def valid_kwargs(self, **overrides):
        kwargs = {
            "scenario_id": "unit-1",
            "label": "unit-case",
            "order_id": "ORD-1",
            "business_operation_id": "RFND-1",
            "attempt_ids": ["ATT-1"],
            "order_age_days": 5,
            "authoritative_window_days": 14,
            "cached_window_days": 14,
            "refund_cents": 1000,
        }
        kwargs.update(overrides)
        return kwargs

    def test_derives_age_class_and_policy_evidence(self):
        inside = env.build_scenario(**self.valid_kwargs(order_age_days=5))
        self.assertEqual(inside["age_class"], "inside")
        self.assertEqual(inside["policy_evidence"], "fresh")
        self.assertFalse(inside["retry_after_lost_ack"])

        boundary = env.build_scenario(**self.valid_kwargs(
            order_age_days=14, cached_window_days=30))
        self.assertEqual(boundary["age_class"], "boundary")
        self.assertEqual(boundary["policy_evidence"], "stale_wider")

        outside = env.build_scenario(**self.valid_kwargs(
            order_age_days=15, cached_window_days=7,
            attempt_ids=["ATT-1", "ATT-2"]))
        self.assertEqual(outside["age_class"], "outside")
        self.assertEqual(outside["policy_evidence"], "stale_narrower")
        self.assertTrue(outside["retry_after_lost_ack"])

    def test_zero_age_is_allowed(self):
        scenario = env.build_scenario(**self.valid_kwargs(order_age_days=0))
        self.assertEqual(scenario["order_age_days"], 0)

    def test_rejects_negative_age_and_other_out_of_range_numbers(self):
        rejected = [
            {"order_age_days": -1},
            {"order_age_days": -14},
            {"authoritative_window_days": 0},
            {"authoritative_window_days": -14},
            {"cached_window_days": 0},
            {"cached_window_days": -1},
            {"refund_cents": 0},
            {"refund_cents": -12900},
        ]
        for overrides in rejected:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    env.build_scenario(**self.valid_kwargs(**overrides))

    def test_rejects_non_integer_and_boolean_numbers(self):
        for overrides in ({"order_age_days": 5.0}, {"order_age_days": "5"},
                          {"refund_cents": True}, {"refund_cents": None},
                          {"cached_window_days": 14.5}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    env.build_scenario(**self.valid_kwargs(**overrides))

    def test_rejects_bad_identifiers_and_attempt_lists(self):
        for overrides in ({"attempt_ids": []},
                          {"attempt_ids": ["ATT-1", "ATT-1"]},
                          {"attempt_ids": ["ATT-1", "ATT-2", "ATT-3"]},
                          {"attempt_ids": "ATT-1"},
                          {"attempt_ids": [7]},
                          {"order_id": ""},
                          {"order_id": "   "},
                          {"business_operation_id": None},
                          {"scenario_id": "x" * 65}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    env.build_scenario(**self.valid_kwargs(**overrides))


class ProbeCatalogTests(unittest.TestCase):
    def test_catalog_exposes_exactly_the_specified_ids(self):
        catalog = env.probe_catalog()
        self.assertEqual([entry["id"] for entry in catalog],
                         ["incident", "recent_order", "expired_order",
                          "lost_ack_retry", "policy_boundary",
                          "stale_cache_control"])

    def test_catalog_entries_carry_ids_and_descriptions_only(self):
        for entry in env.probe_catalog():
            with self.subTest(probe=entry["id"]):
                self.assertEqual(set(entry), {"id", "description"})
                self.assertGreater(len(entry["description"]), 20)

    def test_catalog_does_not_leak_outcomes(self):
        blob = json.dumps(env.probe_catalog()).lower()
        for leak in ("passed", "expected", "cents", "deny_all",
                     "business_operation", "idempotency"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, blob)

    def test_probe_inputs_vary_amounts_and_identifiers(self):
        scenarios = [env.run_probe(REPAIR, entry["id"])["inputs"]
                     for entry in env.probe_catalog()]
        self.assertEqual(len({s["business_operation_id"] for s in scenarios}),
                         len(scenarios))
        self.assertGreaterEqual(len({s["refund_cents"] for s in scenarios}), 5)
        self.assertGreaterEqual(
            len({s["authoritative_window_days"] for s in scenarios}), 3)
        self.assertEqual({s["policy_evidence"] for s in scenarios},
                         {"fresh", "stale_wider", "stale_narrower"})

    def test_run_probe_rejects_unknown_probe_id(self):
        for probe_id in ("unknown", "", None, 7, "INCIDENT"):
            with self.subTest(probe_id=probe_id):
                with self.assertRaises(ValueError):
                    env.run_probe(REPAIR, probe_id)

    def test_run_probe_rejects_invalid_config(self):
        with self.assertRaises(ValueError):
            env.run_probe({"policy_source": "current"}, "incident")


class BaselineAndShortcutTests(unittest.TestCase):
    def test_baseline_fails_the_reported_incident(self):
        result = env.run_probe(env.BASELINE, "incident")
        self.assertFalse(result["passed"])
        self.assertIn("false_refund", result["violations"])
        self.assertEqual(result["observed"]["paid_cents"], 12900)
        self.assertEqual(result["expected"]["paid_cents"], 0)
        self.assertEqual(result["unexpected_cents"], 12900)

    def test_baseline_fails_the_independent_suite(self):
        report = env.verify_candidate(env.BASELINE)
        self.assertFalse(report["passed"])
        self.assertGreater(report["failures"], 0)
        self.assertGreater(report["false_refunds"], 0)
        self.assertGreater(report["missed_refunds"], 0)
        self.assertGreater(report["duplicate_payments"], 0)
        self.assertGreater(report["unexpected_cents"], 0)

    def test_shortcut_passes_the_reported_example_but_fails_a_valid_customer(self):
        for probe_id in ("incident", "expired_order"):
            with self.subTest(probe=probe_id):
                passing = env.run_probe(env.SHORTCUT, probe_id)
                self.assertTrue(passing["passed"])
                self.assertEqual(passing["observed"]["paid_cents"], 0)

        broken = env.run_probe(env.SHORTCUT, "recent_order")
        self.assertFalse(broken["passed"])
        self.assertIn("missed_refund", broken["violations"])
        self.assertEqual(broken["expected"]["paid_cents"], 4575)
        self.assertEqual(broken["observed"]["payment_count"], 0)

    def test_shortcut_fails_the_independent_suite_by_denying_valid_refunds(self):
        report = env.verify_candidate(env.SHORTCUT)
        self.assertFalse(report["passed"])
        self.assertGreater(report["missed_refunds"], 0)
        self.assertEqual(report["false_refunds"], 0)
        self.assertEqual(report["duplicate_payments"], 0)


class ReplayAndRepairTests(unittest.TestCase):
    def test_current_policy_alone_still_fails_the_replay(self):
        result = env.run_probe(HALF_FIX, "lost_ack_retry")
        self.assertFalse(result["passed"])
        self.assertIn("duplicate_payment", result["violations"])
        self.assertEqual(result["observed"]["payment_count"], 2)
        self.assertEqual(result["observed"]["paid_cents"], 42000)
        self.assertEqual(result["expected"]["paid_cents"], 21000)
        self.assertEqual(result["duplicate_payments"], 1)

    def test_current_policy_alone_fixes_the_policy_cases(self):
        for probe_id in ("incident", "recent_order", "expired_order",
                         "policy_boundary", "stale_cache_control"):
            with self.subTest(probe=probe_id):
                self.assertTrue(env.run_probe(HALF_FIX, probe_id)["passed"])

    def test_current_policy_alone_fails_the_independent_suite_on_duplicates(self):
        report = env.verify_candidate(HALF_FIX)
        self.assertFalse(report["passed"])
        self.assertGreater(report["duplicate_payments"], 0)
        self.assertEqual(report["false_refunds"], 0)
        self.assertEqual(report["missed_refunds"], 0)

    def test_retry_keeps_the_business_operation_and_changes_the_attempt(self):
        inputs = env.run_probe(REPAIR, "lost_ack_retry")["inputs"]
        self.assertTrue(inputs["retry_after_lost_ack"])
        self.assertEqual(len(inputs["attempt_ids"]), 2)
        self.assertNotEqual(inputs["attempt_ids"][0], inputs["attempt_ids"][1])

    def test_acknowledgement_is_lost_only_after_the_payment_succeeded(self):
        steps = [event["step"]
                 for event in env.run_probe(HALF_FIX, "lost_ack_retry")["events"]]
        self.assertIn("payment_executed", steps)
        self.assertIn("acknowledgement_lost", steps)
        self.assertLess(steps.index("payment_executed"),
                        steps.index("acknowledgement_lost"))
        self.assertLess(steps.index("acknowledgement_lost"),
                        steps.index("retry_dispatched"))
        self.assertEqual(steps.count("payment_executed"), 2)

    def test_business_operation_key_deduplicates_the_duplicate_side_effect(self):
        result = env.run_probe(REPAIR, "lost_ack_retry")
        steps = [event["step"] for event in result["events"]]
        self.assertTrue(result["passed"])
        self.assertEqual(steps.count("payment_executed"), 1)
        self.assertEqual(steps.count("payment_deduplicated"), 1)
        self.assertEqual(result["observed"]["payment_count"], 1)
        self.assertEqual(result["duplicate_payments"], 0)
        self.assertEqual(len(result["observed"]["payments"]), 1)

    def test_exact_window_boundary_is_refundable(self):
        inputs = env.run_probe(REPAIR, "policy_boundary")["inputs"]
        self.assertEqual(inputs["order_age_days"],
                         inputs["authoritative_window_days"])
        self.assertEqual(inputs["age_class"], "boundary")

        repaired = env.run_probe(REPAIR, "policy_boundary")
        self.assertTrue(repaired["passed"])
        self.assertEqual(repaired["observed"]["paid_cents"], 10000)

        narrow_cache = env.run_probe(env.BASELINE, "policy_boundary")
        self.assertFalse(narrow_cache["passed"])
        self.assertIn("missed_refund", narrow_cache["violations"])

    def test_repair_passes_every_probe(self):
        for entry in env.probe_catalog():
            with self.subTest(probe=entry["id"]):
                self.assertTrue(env.run_probe(REPAIR, entry["id"])["passed"])

    def test_repair_passes_the_independent_suite(self):
        report = env.verify_candidate(REPAIR, seed=env.DEFAULT_SEED, count=80)
        self.assertTrue(report["passed"])
        self.assertEqual(report["total"], 80)
        self.assertEqual(report["passes"], 80)
        self.assertEqual(report["failures"], 0)
        self.assertEqual(report["false_refunds"], 0)
        self.assertEqual(report["missed_refunds"], 0)
        self.assertEqual(report["duplicate_payments"], 0)
        self.assertEqual(report["unexpected_cents"], 0)
        self.assertEqual(report["first_failures"], [])


class VerificationSuiteTests(unittest.TestCase):
    def test_report_exposes_the_required_fields(self):
        report = env.verify_candidate(env.BASELINE)
        for key in ("passed", "total", "passes", "failures", "false_refunds",
                    "missed_refunds", "duplicate_payments", "unexpected_cents",
                    "first_failures", "cases_sha256"):
            with self.subTest(key=key):
                self.assertIn(key, report)
        self.assertIsInstance(report["passed"], bool)
        self.assertEqual(report["passes"] + report["failures"], report["total"])
        self.assertEqual(len(report["cases_sha256"]), 64)

    def test_at_most_three_failure_cases_are_detailed(self):
        report = env.verify_candidate(env.BASELINE)
        self.assertEqual(len(report["first_failures"]), 3)
        for failure in report["first_failures"]:
            with self.subTest(case=failure["scenario"]["scenario_id"]):
                self.assertTrue(failure["violations"])
                self.assertIn("Contract violated", failure["explanation"])
                self.assertIn("scenario", failure)
                self.assertIn("expected", failure)
                self.assertIn("observed", failure)

    def test_generated_cases_cover_the_required_variety(self):
        coverage = env.verify_candidate(REPAIR)["coverage"]
        self.assertGreaterEqual(len(coverage["authoritative_windows"]), 3)
        self.assertEqual(set(coverage["policy_evidence"]),
                         {"fresh", "stale_wider", "stale_narrower"})
        self.assertEqual(set(coverage["age_classes"]),
                         {"inside", "boundary", "outside"})
        for count in coverage["policy_evidence"].values():
            self.assertGreater(count, 0)
        self.assertGreater(coverage["retry_cases"], 0)
        self.assertLess(coverage["retry_cases"], 80)
        self.assertGreater(coverage["distinct_refund_amounts"], 20)
        self.assertEqual(coverage["distinct_business_operations"], 80)
        self.assertEqual(coverage["generation_strata_covered"],
                         coverage["generation_strata_available"])
        self.assertGreaterEqual(coverage["generation_strata_available"], 24)

    def test_sample_size_and_seed_arguments_are_validated(self):
        for count in (0, -1, 1, 79, 5001, 3.5, True, "80", None):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    env.verify_candidate(REPAIR, count=count)
        for seed in (-1, 1.5, "20261010", None, True):
            with self.subTest(seed=seed):
                with self.assertRaises(ValueError):
                    env.verify_candidate(REPAIR, seed=seed)

    def test_verification_rejects_invalid_config_before_running(self):
        with self.assertRaises(ValueError):
            env.verify_candidate({"policy_source": "current", "mode": "fast"})

    def test_larger_sample_sizes_are_accepted(self):
        report = env.verify_candidate(REPAIR, count=128)
        self.assertTrue(report["passed"])
        self.assertEqual(report["total"], 128)


class DeterminismTests(unittest.TestCase):
    def test_probe_replay_is_stable(self):
        for config in (env.BASELINE, env.SHORTCUT, HALF_FIX, REPAIR):
            for entry in env.probe_catalog():
                with self.subTest(config=config, probe=entry["id"]):
                    first = env.run_probe(config, entry["id"])
                    second = env.run_probe(config, entry["id"])
                    self.assertEqual(first, second)

    def test_each_probe_run_uses_an_isolated_ledger(self):
        # A ledger shared between runs would silently deduplicate the second
        # call and report zero payments.
        first = env.run_probe(REPAIR, "lost_ack_retry")
        second = env.run_probe(REPAIR, "lost_ack_retry")
        self.assertEqual(first["observed"]["payment_count"], 1)
        self.assertEqual(second["observed"]["payment_count"], 1)

    def test_verification_replay_is_stable_for_the_same_seed(self):
        for config in (env.BASELINE, REPAIR):
            with self.subTest(config=config):
                first = env.verify_candidate(config, seed=env.DEFAULT_SEED)
                second = env.verify_candidate(config, seed=env.DEFAULT_SEED)
                self.assertEqual(first, second)
                self.assertEqual(first["cases_sha256"], second["cases_sha256"])

    def test_case_digest_tracks_the_generated_set_not_the_config(self):
        baseline = env.verify_candidate(env.BASELINE, seed=env.DEFAULT_SEED)
        repair = env.verify_candidate(REPAIR, seed=env.DEFAULT_SEED)
        self.assertEqual(baseline["cases_sha256"], repair["cases_sha256"])
        wider = env.verify_candidate(REPAIR, seed=env.DEFAULT_SEED, count=128)
        self.assertNotEqual(repair["cases_sha256"], wider["cases_sha256"])


class UnseenSeedTests(unittest.TestCase):
    """The verdicts must not depend on the one seed used during development."""

    UNSEEN_SEEDS = (0, 777, 31337, 2 ** 31 - 1)

    def test_unseen_seeds_generate_different_cases(self):
        digests = {env.verify_candidate(REPAIR, seed=seed)["cases_sha256"]
                   for seed in self.UNSEEN_SEEDS}
        digests.add(env.verify_candidate(REPAIR)["cases_sha256"])
        self.assertEqual(len(digests), len(self.UNSEEN_SEEDS) + 1)

    def test_repair_passes_on_unseen_seeds(self):
        for seed in self.UNSEEN_SEEDS:
            with self.subTest(seed=seed):
                report = env.verify_candidate(REPAIR, seed=seed, count=128)
                self.assertTrue(report["passed"])
                self.assertEqual(report["unexpected_cents"], 0)

    def test_baseline_and_shortcut_still_fail_on_unseen_seeds(self):
        for seed in self.UNSEEN_SEEDS:
            for config in (env.BASELINE, env.SHORTCUT, HALF_FIX):
                with self.subTest(seed=seed, config=config):
                    self.assertFalse(
                        env.verify_candidate(config, seed=seed)["passed"])


class IncidentIntakeTests(unittest.TestCase):
    def test_intake_describes_contract_configuration_and_both_symptoms(self):
        incident = env.read_incident()
        self.assertGreaterEqual(len(incident["business_contract"]), 3)
        self.assertEqual(incident["running_config"], env.BASELINE)

        symptoms = {item["symptom_id"]: item
                    for item in incident["reported_symptoms"]}
        self.assertEqual(len(symptoms), 2)
        unauthorised = symptoms["unauthorised-refund-1"]["observations"]
        self.assertEqual(unauthorised["amount_paid_cents"], 12900)
        self.assertEqual(unauthorised["order_age_days_at_request"], 24)
        self.assertEqual(unauthorised["authoritative_return_window_days"], 14)
        ack_loss = symptoms["acknowledgement-loss-1"]["observations"]
        self.assertEqual(ack_loss["ledger_entries"], 2)
        self.assertEqual(ack_loss["amount_requested_cents"], 21000)
        self.assertEqual(ack_loss["amount_paid_cents"], 42000)

    def test_intake_does_not_embed_the_repair_or_a_diagnosis(self):
        incident = env.read_incident()
        narrative = dict(incident)
        # The baseline configuration is supplied on purpose; the surrounding
        # narrative must not name the repair or the cause.
        narrative.pop("running_config")
        narrative.pop("config_surface")
        blob = json.dumps(narrative).lower()
        for leak in ("deny_all", "business_operation", "idempoten", "stale",
                     "cache", "policy_source", "root cause", "diagnos"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, blob)

    def test_intake_running_config_is_a_copy(self):
        incident = env.read_incident()
        incident["running_config"]["policy_source"] = "current"
        self.assertEqual(env.BASELINE["policy_source"], "cache")
        self.assertEqual(env.read_incident()["running_config"], env.BASELINE)


class SerializationTests(unittest.TestCase):
    def round_trip(self, value):
        return json.loads(json.dumps(value))

    def test_every_source_is_json_serializable(self):
        payloads = {
            "incident": env.read_incident(),
            "catalog": env.probe_catalog(),
            "verification": env.verify_candidate(env.BASELINE),
            "repair_verification": env.verify_candidate(REPAIR),
        }
        for config in (env.BASELINE, env.SHORTCUT, HALF_FIX, REPAIR):
            for entry in env.probe_catalog():
                key = f"{config['policy_source']}/{entry['id']}"
                payloads[key] = env.run_probe(config, entry["id"])
        for name, payload in payloads.items():
            with self.subTest(source=name):
                self.assertEqual(self.round_trip(payload), payload)

    def test_results_state_their_claim_boundary(self):
        probe = env.run_probe(env.BASELINE, "incident")
        report = env.verify_candidate(env.BASELINE)
        for payload in (probe, report):
            self.assertIn("synthetic", payload["units"].lower())
            self.assertIn("not a production safety guarantee",
                          payload["claim_boundary"])
            self.assertIn("without running the configured workflow",
                          payload["oracle"])


if __name__ == "__main__":
    unittest.main()
