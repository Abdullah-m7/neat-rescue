"""Bounded synthetic sandbox for the NeatRescue refund-workflow incident.

Everything in this module is a simulation written for this project.  There are
no network calls, no model calls, no subprocesses, and no real orders,
customers, payments, or credentials.  Amounts are exact integer cents; "SAR" is
a scenario label only, never a foreign-exchange calculation.

A passing verification here is evidence about the generated synthetic scenarios
and nothing more.  It is not evidence of production safety.

Three code paths are kept deliberately separate so that a repair cannot be
graded by the thing being repaired:

* ``_execute_refund_workflow`` is the *target*: the support refund workflow as
  driven by a candidate configuration.
* ``_authoritative_outcome`` is the *oracle*: what the business contract
  requires, computed from the authoritative return policy and exactly-once
  payment semantics.  It never calls the target or reads the configuration.
* ``_compare`` grades one against the other and classifies the violation.
"""
from __future__ import annotations

import hashlib
import json
import random

POLICY_SOURCES = ("cache", "current", "deny_all")
IDEMPOTENCY_KEYS = ("attempt", "business_operation")
CONFIG_KEYS = ("idempotency_key", "policy_source")

BASELINE = {"policy_source": "cache", "idempotency_key": "attempt"}
SHORTCUT = {"policy_source": "deny_all", "idempotency_key": "attempt"}

DEFAULT_SEED = 20261010
DEFAULT_CASE_COUNT = 80
MIN_CASE_COUNT = 80
MAX_CASE_COUNT = 5000
MAX_SEED = 2 ** 63 - 1

UNITS_NOTE = (
    "Amounts are synthetic integer cents; 'SAR' is a scenario label, not a "
    "currency conversion."
)
CLAIM_NOTE = (
    "Synthetic sandbox result over generated scenarios only; not a production "
    "safety guarantee."
)
ORACLE_NOTE = (
    "Expected outcomes come from the authoritative return policy and "
    "exactly-once payment per business operation, computed without running the "
    "configured workflow."
)


# --------------------------------------------------------------------------
# input validation
# --------------------------------------------------------------------------

def _require_int(value: object, name: str, minimum: int, maximum: int) -> int:
    """Return ``value`` as an int, or raise ValueError with a usable message."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return int(value)


def _require_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError(f"{name} must be a non-empty string of at most 64 characters")
    return value


def validate_config(config: object) -> dict:
    """Validate a candidate configuration and return a normalized copy.

    The configuration surface is deliberately tiny: exactly two keys, each from
    a closed set.  Anything else raises ValueError rather than being coerced,
    so an investigator cannot smuggle in new behaviour.
    """
    if not isinstance(config, dict):
        raise ValueError(f"config must be a dict, got {type(config).__name__}")
    present = set(config)
    allowed = set(CONFIG_KEYS)
    if present != allowed:
        # repr keeps the message printable when a key is not even a string.
        unknown = sorted(map(repr, present - allowed))
        missing = sorted(allowed - present)
        raise ValueError(
            f"config must have exactly the keys {list(CONFIG_KEYS)}; "
            f"unknown={unknown} missing={missing}"
        )
    for key, choices in (("policy_source", POLICY_SOURCES),
                         ("idempotency_key", IDEMPOTENCY_KEYS)):
        value = config[key]
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"{key} must be one of {list(choices)}, got {value!r}")
    return {"policy_source": config["policy_source"],
            "idempotency_key": config["idempotency_key"]}


def config_digest(config: object) -> str:
    """sha256 of the canonical normalized configuration."""
    canonical = json.dumps(validate_config(config), sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_scenario(*, scenario_id: str, label: str, order_id: str,
                   business_operation_id: str, attempt_ids: list,
                   order_age_days: int, authoritative_window_days: int,
                   cached_window_days: int, refund_cents: int) -> dict:
    """Validate one refund scenario and derive its classification fields.

    Used both by the fixed probe catalog and by the generated verification
    suite, so every scenario in the sandbox is range-checked the same way.
    A retry is expressed as a second attempt id under the same business
    operation id; there is no separate retry flag to fall out of sync.
    """
    if not isinstance(attempt_ids, (list, tuple)) or not 1 <= len(attempt_ids) <= 2:
        raise ValueError("attempt_ids must be a list of one or two attempt ids")
    attempts = [_require_id(value, "attempt_id") for value in attempt_ids]
    if len(set(attempts)) != len(attempts):
        raise ValueError("a retry must use a new attempt id, not a repeated one")
    authoritative = _require_int(authoritative_window_days,
                                 "authoritative_window_days", 1, 3650)
    cached = _require_int(cached_window_days, "cached_window_days", 1, 3650)
    age = _require_int(order_age_days, "order_age_days", 0, 36500)
    cents = _require_int(refund_cents, "refund_cents", 1, 100_000_000)
    if age == authoritative:
        age_class = "boundary"
    elif age < authoritative:
        age_class = "inside"
    else:
        age_class = "outside"
    if cached == authoritative:
        policy_evidence = "fresh"
    elif cached > authoritative:
        policy_evidence = "stale_wider"
    else:
        policy_evidence = "stale_narrower"
    return {
        "scenario_id": _require_id(scenario_id, "scenario_id"),
        "label": _require_id(label, "label"),
        "order_id": _require_id(order_id, "order_id"),
        "business_operation_id": _require_id(business_operation_id,
                                             "business_operation_id"),
        "attempt_ids": attempts,
        "retry_after_lost_ack": len(attempts) > 1,
        "order_age_days": age,
        "authoritative_window_days": authoritative,
        "cached_window_days": cached,
        "refund_cents": cents,
        "age_class": age_class,
        "policy_evidence": policy_evidence,
    }


# --------------------------------------------------------------------------
# target workflow (driven by the candidate configuration)
# --------------------------------------------------------------------------

def _execute_refund_workflow(config: dict, scenario: dict) -> tuple:
    """Run the configured refund workflow once; return (observed, events).

    The payment ledger is created here, so every call — every probe and every
    verification case — settles against its own isolated ledger.
    """
    source = config["policy_source"]
    key_strategy = config["idempotency_key"]
    if source == "cache":
        window = scenario["cached_window_days"]
    elif source == "current":
        window = scenario["authoritative_window_days"]
    else:
        window = None

    ledger: dict = {}
    payments: list = []
    events = [{
        "step": "policy_lookup",
        "policy_source": source,
        "return_window_days": window,
        "detail": ("the configured policy source refuses every refund without "
                   "reading a return window")
        if window is None else
        (f"the configured policy source reports a {window}-day return window"),
    }]

    attempts = scenario["attempt_ids"]
    for position, attempt_id in enumerate(attempts, start=1):
        events.append({
            "step": "refund_requested",
            "attempt": position,
            "attempt_id": attempt_id,
            "business_operation_id": scenario["business_operation_id"],
            "order_id": scenario["order_id"],
            "order_age_days": scenario["order_age_days"],
            "amount_cents": scenario["refund_cents"],
        })
        eligible = window is not None and scenario["order_age_days"] <= window
        events.append({
            "step": "eligibility_decision",
            "attempt": position,
            "eligible": eligible,
            "detail": f"policy source {source} denies without an age comparison"
            if window is None else
            (f"order age {scenario['order_age_days']} days compared against the "
             f"{window}-day window read from {source}"),
        })
        paid_this_attempt = False
        if eligible:
            ledger_key = (f"attempt:{attempt_id}" if key_strategy == "attempt"
                          else f"operation:{scenario['business_operation_id']}")
            if ledger_key in ledger:
                events.append({
                    "step": "payment_deduplicated",
                    "attempt": position,
                    "idempotency_key": ledger_key,
                    "detail": "the ledger already holds a payment for this key",
                })
            else:
                ledger[ledger_key] = scenario["refund_cents"]
                payments.append({
                    "attempt": position,
                    "attempt_id": attempt_id,
                    "idempotency_key": ledger_key,
                    "amount_cents": scenario["refund_cents"],
                })
                paid_this_attempt = True
                events.append({
                    "step": "payment_executed",
                    "attempt": position,
                    "idempotency_key": ledger_key,
                    "amount_cents": scenario["refund_cents"],
                    "detail": "money left the synthetic ledger",
                })
        else:
            events.append({
                "step": "refund_denied",
                "attempt": position,
                "amount_cents": 0,
            })
        if position < len(attempts):
            events.append({
                "step": "acknowledgement_lost" if paid_this_attempt
                else "response_lost",
                "attempt": position,
                "detail": ("the payment already succeeded, but its "
                           "acknowledgement never reached the caller")
                if paid_this_attempt else
                "the denial response never reached the caller",
            })
            events.append({
                "step": "retry_dispatched",
                "attempt": position + 1,
                "next_attempt_id": attempts[position],
                "business_operation_id": scenario["business_operation_id"],
                "detail": ("the caller retries the same business operation "
                           "under a new attempt id"),
            })

    observed = {
        "paid_cents": sum(item["amount_cents"] for item in payments),
        "payment_count": len(payments),
        "refund_paid": bool(payments),
        "payments": payments,
    }
    return observed, events


# --------------------------------------------------------------------------
# independent oracle
# --------------------------------------------------------------------------

def _authoritative_outcome(scenario: dict) -> dict:
    """Ground truth for one scenario, derived from the business contract only."""
    within_window = (scenario["order_age_days"]
                     <= scenario["authoritative_window_days"])
    return {
        "paid_cents": scenario["refund_cents"] if within_window else 0,
        "payment_count": 1 if within_window else 0,
        "refund_paid": within_window,
        "basis": (f"authoritative return window "
                  f"{scenario['authoritative_window_days']} days, order age "
                  f"{scenario['order_age_days']} days, at most one payment per "
                  f"business operation"),
    }


def _compare(expected: dict, observed: dict) -> tuple:
    """Grade observed against expected; return (passed, violations, delta)."""
    violations = []
    if expected["payment_count"] == 0 and observed["payment_count"] > 0:
        violations.append("false_refund")
    if expected["payment_count"] > 0 and observed["payment_count"] == 0:
        violations.append("missed_refund")
    if observed["payment_count"] > 1:
        violations.append("duplicate_payment")
    passed = (observed["paid_cents"] == expected["paid_cents"]
              and observed["payment_count"] == expected["payment_count"])
    return passed, violations, abs(observed["paid_cents"] - expected["paid_cents"])


def _explain(scenario: dict, expected: dict, observed: dict,
             violations: list) -> str:
    """Plain-language summary of one graded case. Mechanical, not introspective."""
    age = scenario["order_age_days"]
    window = scenario["authoritative_window_days"]
    if not violations:
        if expected["payment_count"] == 0:
            return (f"No refund was paid, which matches the contract: an order "
                    f"aged {age} days falls outside the authoritative "
                    f"{window}-day return window.")
        return (f"Exactly one payment of {observed['paid_cents']} cents was "
                f"executed, which matches the contract for an order aged {age} "
                f"days inside the authoritative {window}-day return window.")
    parts = []
    if "false_refund" in violations:
        parts.append(f"{observed['paid_cents']} cents were paid although the "
                     f"order is {age} days old, outside the authoritative "
                     f"{window}-day return window")
    if "missed_refund" in violations:
        parts.append(f"no refund was paid although the order is {age} days old, "
                     f"within the authoritative {window}-day return window, so "
                     f"{expected['paid_cents']} cents were owed")
    if "duplicate_payment" in violations:
        parts.append(f"business operation {scenario['business_operation_id']} "
                     f"executed {observed['payment_count']} payments totalling "
                     f"{observed['paid_cents']} cents instead of one payment of "
                     f"{expected['paid_cents']} cents")
    return "Contract violated: " + "; ".join(parts) + "."


def _grade(config: dict, scenario: dict) -> dict:
    observed, events = _execute_refund_workflow(config, scenario)
    expected = _authoritative_outcome(scenario)
    passed, violations, delta = _compare(expected, observed)
    return {
        "scenario": scenario,
        "events": events,
        "expected": expected,
        "observed": observed,
        "passed": passed,
        "violations": violations,
        "unexpected_cents": delta,
        "explanation": _explain(scenario, expected, observed, violations),
    }


# --------------------------------------------------------------------------
# probe catalog
# --------------------------------------------------------------------------

_PROBES = (
    {
        "id": "incident",
        "description": ("The reported request: an aged order whose refund was "
                        "later flagged as unauthorised."),
        "scenario": {
            "label": "reported-incident",
            "order_id": "ORD-558120",
            "business_operation_id": "RFND-558120-A",
            "attempt_ids": ["ATT-558120-1"],
            "order_age_days": 24,
            "authoritative_window_days": 14,
            "cached_window_days": 30,
            "refund_cents": 12900,
        },
    },
    {
        "id": "recent_order",
        "description": ("A legitimate recent return that the workflow is "
                        "required to refund."),
        "scenario": {
            "label": "legitimate-recent-return",
            "order_id": "ORD-203847",
            "business_operation_id": "RFND-203847-A",
            "attempt_ids": ["ATT-203847-1"],
            "order_age_days": 5,
            "authoritative_window_days": 21,
            "cached_window_days": 30,
            "refund_cents": 4575,
        },
    },
    {
        "id": "expired_order",
        "description": ("An order well past the authoritative return window, "
                        "with a different window and amount from the incident."),
        "scenario": {
            "label": "clearly-expired-return",
            "order_id": "ORD-917004",
            "business_operation_id": "RFND-917004-A",
            "attempt_ids": ["ATT-917004-1"],
            "order_age_days": 40,
            "authoritative_window_days": 30,
            "cached_window_days": 45,
            "refund_cents": 8650,
        },
    },
    {
        "id": "lost_ack_retry",
        "description": ("A refund whose acknowledgement is lost after the "
                        "payment already succeeded, followed by an automatic "
                        "retry of the same business operation."),
        "scenario": {
            "label": "acknowledgement-loss-retry",
            "order_id": "ORD-461299",
            "business_operation_id": "RFND-461299-A",
            "attempt_ids": ["ATT-461299-1", "ATT-461299-2"],
            "order_age_days": 3,
            "authoritative_window_days": 14,
            "cached_window_days": 14,
            "refund_cents": 21000,
        },
    },
    {
        "id": "policy_boundary",
        "description": ("An order exactly on the last day of the authoritative "
                        "return window."),
        "scenario": {
            "label": "exact-window-boundary",
            "order_id": "ORD-330561",
            "business_operation_id": "RFND-330561-A",
            "attempt_ids": ["ATT-330561-1"],
            "order_age_days": 14,
            "authoritative_window_days": 14,
            "cached_window_days": 7,
            "refund_cents": 10000,
        },
    },
    {
        "id": "stale_cache_control",
        "description": ("The incident order replayed while the policy evidence "
                        "the workflow can read agrees with the authoritative "
                        "window."),
        "scenario": {
            "label": "incident-order-fresh-evidence",
            "order_id": "ORD-558120",
            "business_operation_id": "RFND-558120-B",
            "attempt_ids": ["ATT-558120-9"],
            "order_age_days": 24,
            "authoritative_window_days": 14,
            "cached_window_days": 14,
            "refund_cents": 12900,
        },
    },
)

PROBE_IDS = tuple(probe["id"] for probe in _PROBES)


def probe_catalog() -> list:
    """Probe ids and descriptions only; no outcomes and no answers."""
    return [{"id": probe["id"], "description": probe["description"]}
            for probe in _PROBES]


def _probe_scenario(probe_id: object) -> dict:
    for probe in _PROBES:
        if probe["id"] == probe_id:
            return build_scenario(scenario_id=probe["id"], **probe["scenario"])
    raise ValueError(f"unknown probe_id {probe_id!r}; "
                     f"available ids are {list(PROBE_IDS)}")


def run_probe(config: object, probe_id: object) -> dict:
    """Run one diagnostic probe against a candidate configuration."""
    normalized = validate_config(config)
    scenario = _probe_scenario(probe_id)
    graded = _grade(normalized, scenario)
    return {
        "probe_id": probe_id,
        "config": normalized,
        "config_sha256": config_digest(normalized),
        "inputs": graded["scenario"],
        "events": graded["events"],
        "expected": graded["expected"],
        "observed": graded["observed"],
        "passed": graded["passed"],
        "violations": graded["violations"],
        "unexpected_cents": graded["unexpected_cents"],
        "duplicate_payments": max(0, graded["observed"]["payment_count"] - 1),
        "explanation": graded["explanation"],
        "oracle": ORACLE_NOTE,
        "units": UNITS_NOTE,
        "claim_boundary": CLAIM_NOTE,
    }


# --------------------------------------------------------------------------
# generated verification suite
# --------------------------------------------------------------------------

_WINDOWS = (7, 14, 21, 30, 45)
_EVIDENCE = ("fresh", "stale_wider", "stale_narrower")
_AGE_SHAPES = ("inside", "boundary", "just_outside", "far_outside")
_RETRY_SHAPES = (False, True)
_STRATA = tuple((evidence, age_shape, retry)
                for evidence in _EVIDENCE
                for age_shape in _AGE_SHAPES
                for retry in _RETRY_SHAPES)


def _generate_cases(seed: int, count: int) -> list:
    """Deterministically generate a varied scenario set for one (seed, count).

    Strata cycle over policy-evidence direction, age shape and retry shape,
    while the authoritative window cycles over a coprime-length tuple, so even
    the smallest allowed suite covers every combination at least three times.
    """
    rng = random.Random(seed)
    cases = []
    for index in range(count):
        evidence, age_shape, retry = _STRATA[index % len(_STRATA)]
        window = _WINDOWS[index % len(_WINDOWS)]
        if age_shape == "inside":
            age = rng.randrange(0, window)
        elif age_shape == "boundary":
            age = window
        elif age_shape == "just_outside":
            age = window + 1
        else:
            age = window + rng.randrange(2, 61)
        if evidence == "fresh":
            cached = window
        elif evidence == "stale_wider":
            cached = window + rng.randrange(1, 31)
        else:
            cached = window - rng.randrange(1, window)
        serial = rng.randrange(100_000, 1_000_000)
        attempts = [f"ATT-{serial}-1"]
        if retry:
            attempts.append(f"ATT-{serial}-2")
        cases.append(build_scenario(
            scenario_id=f"gen-{index:04d}",
            label=f"{evidence}/{age_shape}/{'retry' if retry else 'single'}",
            order_id=f"ORD-{serial}",
            business_operation_id=f"RFND-{serial}-{index:04d}",
            attempt_ids=attempts,
            order_age_days=age,
            authoritative_window_days=window,
            cached_window_days=cached,
            refund_cents=rng.randrange(20, 20_001) * 25,
        ))
    return cases


def _coverage(cases: list) -> dict:
    evidence: dict = {}
    ages: dict = {}
    for case in cases:
        evidence[case["policy_evidence"]] = evidence.get(case["policy_evidence"], 0) + 1
        ages[case["age_class"]] = ages.get(case["age_class"], 0) + 1
    return {
        "authoritative_windows": sorted({case["authoritative_window_days"]
                                         for case in cases}),
        "policy_evidence": evidence,
        "age_classes": ages,
        "retry_cases": sum(1 for case in cases if case["retry_after_lost_ack"]),
        "distinct_refund_amounts": len({case["refund_cents"] for case in cases}),
        "distinct_business_operations": len({case["business_operation_id"]
                                             for case in cases}),
        "generation_strata_covered": len({case["label"] for case in cases}),
        "generation_strata_available": len(_STRATA),
    }


def verify_candidate(config: object, seed: int = DEFAULT_SEED,
                     count: int = DEFAULT_CASE_COUNT) -> dict:
    """Independently test a candidate configuration on generated scenarios.

    Deterministic for a given (config, seed, count).  Every case settles
    against its own isolated payment ledger and is graded by the independent
    oracle, which never consults the configured workflow.
    """
    normalized = validate_config(config)
    seed = _require_int(seed, "seed", 0, MAX_SEED)
    count = _require_int(count, "count", MIN_CASE_COUNT, MAX_CASE_COUNT)
    cases = _generate_cases(seed, count)

    passes = 0
    false_refunds = missed_refunds = duplicate_payments = unexpected_cents = 0
    first_failures: list = []
    for case in cases:
        graded = _grade(normalized, case)
        unexpected_cents += graded["unexpected_cents"]
        if "false_refund" in graded["violations"]:
            false_refunds += 1
        if "missed_refund" in graded["violations"]:
            missed_refunds += 1
        if "duplicate_payment" in graded["violations"]:
            duplicate_payments += 1
        if graded["passed"]:
            passes += 1
        elif len(first_failures) < 3:
            first_failures.append({
                "scenario": graded["scenario"],
                "expected": graded["expected"],
                "observed": graded["observed"],
                "violations": graded["violations"],
                "event_steps": [event["step"] for event in graded["events"]],
                "explanation": graded["explanation"],
            })

    canonical_cases = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    return {
        "config": normalized,
        "config_sha256": config_digest(normalized),
        "seed": seed,
        "count": count,
        "passed": passes == count,
        "total": count,
        "passes": passes,
        "failures": count - passes,
        "false_refunds": false_refunds,
        "missed_refunds": missed_refunds,
        "duplicate_payments": duplicate_payments,
        "unexpected_cents": unexpected_cents,
        "first_failures": first_failures,
        "cases_sha256": hashlib.sha256(canonical_cases.encode("utf-8")).hexdigest(),
        "coverage": _coverage(cases),
        "oracle": ORACLE_NOTE,
        "units": UNITS_NOTE,
        "claim_boundary": CLAIM_NOTE,
    }


# --------------------------------------------------------------------------
# incident intake
# --------------------------------------------------------------------------

def read_incident() -> dict:
    """Observable intake material: contract, running configuration, symptoms.

    Deliberately contains no diagnosis and no repair: only what an on-call
    engineer would have in front of them.
    """
    return {
        "incident_id": "NR-2026-1010-01",
        "workflow": "support refund decision and payment",
        "business_contract": [
            "A refund is authorised only when the order age is within the "
            "return window published by the authoritative policy service at "
            "the moment of the request.",
            "The return window is inclusive: an order on the final day of the "
            "window is still refundable.",
            "A refund request that is retried must still move money at most "
            "once for the same refund request.",
            "Amounts are exact integer cents and must match to the cent.",
        ],
        "running_config": dict(BASELINE),
        "config_surface": {
            "policy_source": list(POLICY_SOURCES),
            "idempotency_key": list(IDEMPOTENCY_KEYS),
        },
        "reported_symptoms": [
            {
                "symptom_id": "unauthorised-refund-1",
                "summary": ("A refund was paid and later flagged by finance as "
                            "not authorised."),
                "observations": {
                    "order_id": "ORD-558120",
                    "order_age_days_at_request": 24,
                    "authoritative_return_window_days": 14,
                    "amount_paid_cents": 12900,
                    "ledger_entries": 1,
                },
            },
            {
                "symptom_id": "acknowledgement-loss-1",
                "summary": ("A retried refund request left two entries in the "
                            "payment ledger."),
                "observations": {
                    "order_id": "ORD-461299",
                    "refund_request_id": "RFND-461299-A",
                    "amount_requested_cents": 21000,
                    "amount_paid_cents": 42000,
                    "ledger_entries": 2,
                    "caller_received_acknowledgement": False,
                },
            },
        ],
        "available_tools": ["validate_config", "probe_catalog", "run_probe",
                            "verify_candidate", "config_digest"],
        "notes": [
            UNITS_NOTE,
            "Synthetic reconstruction: no real customers, orders, payments, "
            "credentials, or production access are involved.",
            "No cause and no repair are supplied here; both must be "
            "established from probe and verification evidence.",
        ],
    }
