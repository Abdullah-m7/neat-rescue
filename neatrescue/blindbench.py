"""Blind source-repair benchmark for the NeatRescue returns adapter.

The solver sees a contract, a symptom and a faulty source. It never sees the
reference oracle, the mutation ids, or the final evaluation seed.
"""

import ast
import hashlib
import json
import random
from copy import deepcopy

__all__ = [
    "CONTRACT", "PROBES", "FUNCTION_NAMES", "SIGNATURES", "PUBLIC_INCIDENT_KEYS",
    "make_incident", "reference_source", "validate_source", "evaluate", "smoke_example",
]

PROBES = ["eligibility", "partial_refund", "tenant_retry", "inventory_replay"]

SIGNATURES = {
    "eligible": ("order", "policy"),
    "refund_cents": ("order",),
    "operation_key": ("event",),
    "inventory_after": ("stock", "qty", "already_applied"),
}
FUNCTION_NAMES = tuple(SIGNATURES)
PUBLIC_INCIDENT_KEYS = ("incident_id", "contract", "symptom", "faulty_source")

SYMPTOM = (
    "Customers report wrong answers from the returns desk adapter: some return windows and "
    "refund amounts come back unexpected, and retried tool calls are not always treated as "
    "the same operation."
)

CONTRACT = {
    "domain": "returns desk adapter: four pure Python functions behind tool calls",
    "signatures": {
        "eligible": "eligible(order, policy) -> bool",
        "refund_cents": "refund_cents(order) -> int",
        "operation_key": "operation_key(event) -> str",
        "inventory_after": "inventory_after(stock, qty, already_applied) -> int",
    },
    "inputs": {
        "order": "eligible: age_days, cached_window_days; refund_cents: requested_cents, paid_cents, already_refunded_cents (all int)",
        "policy": "window_days: int, authoritative and inclusive",
        "event": "tenant_id, refund_id, attempt_id, order_id (nonempty alphanumeric str <=30)",
        "inventory": "stock nonnegative int, qty int, already_applied bool",
    },
    "rules": {
        "eligible": "True only when order age is within the policy window; negative age is invalid",
        "refund_cents": "at most the request and at most the remaining paid balance; never negative",
        "operation_key": "retries of one logical refund share a key; distinct tenants or refunds must not",
        "inventory_after": "an already-applied request is a no-op; otherwise only a valid, affordable qty lowers stock",
    },
    "output_checks": "strict types: bool for eligible, int for refund_cents and inventory_after, nonempty str for operation_key",
    "syntax_subset": (
        "exactly the four functions above with those positional parameter names; no imports, globals, "
        "classes, decorators, lambdas, loops, comprehensions, recursion, attribute access other than "
        ".get on a parameter, multiplication or power; calls limited to min/max/str/int/len/bool"
    ),
    "result_fields": (
        "evaluate() returns passed, total, passes, failures, by_family, first_failures "
        "(<=3 with input/expected/observed), cases_sha256, source_sha256"
    ),
    "probes": list(PROBES),
}

MAX_SOURCE_CHARS, MAX_NODES, MAX_DEPTH = 6000, 350, 20
MAX_ASSIGNMENTS, MAX_STR_CONST, MAX_INT_CONST = 8, 80, 10**9
SAFE_BUILTINS = {"min": min, "max": max, "str": str, "int": int, "len": len, "bool": bool}
SAFE_CALLS = tuple(SAFE_BUILTINS)

_ALPHA = "abcdefghijklmnopqrstuvwxyz0123456789"
_FAMILY_FUNCTION = dict(zip(PROBES, FUNCTION_NAMES))

# ---------------------------------------------------------------- fixtures

_CORRECT = {
    "eligible": """def eligible(order, policy):
    age = order['age_days']
    limit = policy['window_days']
    if age < 0:
        return False
    return age <= limit
""",
    "refund_cents": """def refund_cents(order):
    want = order['requested_cents']
    paid = order['paid_cents']
    done = order['already_refunded_cents']
    if want <= 0:
        return 0
    left = paid - done
    if left < 0:
        return 0
    return min(want, left)
""",
    "operation_key": """def operation_key(event):
    tenant = event['tenant_id']
    refund = event['refund_id']
    return str(tenant) + ':' + str(refund)
""",
    "inventory_after": """def inventory_after(stock, qty, already_applied):
    if already_applied:
        return stock
    if qty <= 0:
        return stock
    if qty > stock:
        return stock
    return stock - qty
""",
}

# Each fault is an ordered list of single-occurrence text edits to the correct body.
_FAULTS = {
    "eligible": {
        "cached-window": [("policy['window_days']", "order['cached_window_days']")],
        "exclusive-boundary": [("age <= limit", "age < limit")],
        "unguarded-age": [("    if age < 0:\n        return False\n", "")],
    },
    "refund_cents": {
        "ignores-refunded": [
            ("    left = paid - done\n    if left < 0:\n        return 0\n", ""),
            ("min(want, left)", "min(want, paid)"),
            ("    done = order['already_refunded_cents']\n", ""),
        ],
        "unguarded-request": [
            ("    if want <= 0:\n        return 0\n", ""),
            ("    left = paid - done\n    if left < 0:\n        return 0\n", ""),
            ("min(want, left)", "min(want, paid - done)"),
        ],
    },
    "operation_key": {
        "attempt-in-key": [
            ("    return str(tenant)", "    attempt = event['attempt_id']\n    return str(tenant)"),
            ("+ str(refund)", "+ str(refund) + ':' + str(attempt)"),
        ],
        "order-only": [
            ("    tenant = event['tenant_id']\n    refund = event['refund_id']\n"
             "    return str(tenant) + ':' + str(refund)",
             "    target = event['order_id']\n    return str(target)"),
        ],
    },
    "inventory_after": {
        "ignores-replay": [("    if already_applied:\n        return stock\n", "")],
        "accepts-negative": [("    if qty <= 0:\n        return stock\n", "")],
    },
}


def _variant(name, fault):
    source = _CORRECT[name]
    for old, new in _FAULTS[name][fault] if fault != "ok" else ():
        if source.count(old) != 1:
            raise AssertionError("fault {0}/{1} does not apply cleanly".format(name, fault))
        source = source.replace(old, new)
    return source


def _compose(variants):
    return "\n".join(_variant(name, variants[name]) for name in FUNCTION_NAMES)


def reference_source():
    """Private oracle fixture: offline test validation only, never a solver tool."""
    return _compose({name: "ok" for name in FUNCTION_NAMES})


# -------------------------------------------------------------- validation
# Safety boundary: whitelist only, and nothing runs until it passes.


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _plain(name, what):
    _require(isinstance(name, str) and name and not name.startswith("_"),
             "unsupported identifier for {0}: {1!r}".format(what, name))


def _depth(node, level=0):
    children = list(ast.iter_child_nodes(node))
    return max((_depth(child, level + 1) for child in children), default=level)


def _const(value):
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        _require(len(value) <= MAX_STR_CONST, "string constant too long")
    elif isinstance(value, int):
        _require(abs(value) <= MAX_INT_CONST, "integer constant out of range")
    else:
        _require(False, "unsupported constant type: " + type(value).__name__)


# Every node reachable inside a candidate function must be one of these kinds.
_ALLOWED = (
    ast.Assign, ast.If, ast.Return, ast.Name, ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp,
    ast.Compare, ast.IfExp, ast.Subscript, ast.Tuple, ast.List, ast.Call, ast.Attribute,
    ast.Load, ast.Store, ast.Add, ast.Sub, ast.Not, ast.USub, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot,
)


def _body(func, params, names):
    """Whitelist every node in one candidate function, plus its local rules."""
    nodes = [n for n in ast.walk(func) if n is not func and not isinstance(n, (ast.arguments, ast.arg))]
    callees = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    for node in nodes:
        _require(isinstance(node, _ALLOWED), "unsupported syntax: " + type(node).__name__)
        if isinstance(node, ast.Assign):
            _require(len(node.targets) == 1 and isinstance(node.targets[0], ast.Name),
                     "assign to one local name only")
            target = node.targets[0].id
            _require(target not in SAFE_CALLS and target not in FUNCTION_NAMES, "cannot reassign " + target)
        elif isinstance(node, ast.Name):
            _plain(node.id, "name")
            _require(node.id in names or id(node) in callees or not isinstance(node.ctx, ast.Load),
                     "unknown name, parameters and locals only: " + node.id)
        elif isinstance(node, ast.Constant):
            _const(node.value)
        elif isinstance(node, ast.Subscript):
            _require(isinstance(node.value, ast.Name), "subscript a named value only")
            _require(not isinstance(node.slice, ast.Slice), "no slicing")
        elif isinstance(node, ast.Attribute):
            _require(node.attr == "get", "unsupported attribute: " + str(node.attr))
            _require(isinstance(node.value, ast.Name) and node.value.id in params, ".get on a parameter only")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                _require(1 <= len(node.args) <= 2, ".get takes one or two arguments")
            else:
                _require(isinstance(node.func, ast.Name) and node.func.id in SAFE_CALLS,
                         "call to unsupported function")


def _function(node):
    args = node.args
    _require(not node.decorator_list, "decorators are not supported")
    _require(node.returns is None and all(a.annotation is None for a in args.args), "no annotations")
    _require(not (args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg),
             node.name + " takes plain positional parameters")
    _require(not (args.defaults or args.kw_defaults), "default arguments are not supported")
    for arg in args.args:
        _plain(arg.arg, "parameter")
    params = tuple(arg.arg for arg in args.args)
    _require(params == SIGNATURES[node.name],
             "{0} must take {1}, got {2}".format(node.name, SIGNATURES[node.name], params))
    assigns = [child for child in ast.walk(node) if isinstance(child, ast.Assign)]
    _require(len(assigns) <= MAX_ASSIGNMENTS, node.name + " has too many assignments")
    locals_ = {t.id for a in assigns for t in a.targets if isinstance(t, ast.Name)}
    _body(node, set(params), set(params) | locals_)


def validate_source(source):
    """Raise ValueError unless source is in the supported pure-Python subset.

    Narrow syntax whitelist for this benchmark, not a general security sandbox.
    """
    _require(isinstance(source, str), "source must be a string")
    _require(len(source) <= MAX_SOURCE_CHARS, "source too long")
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise ValueError("source does not parse: {0}".format(exc)) from None
    _require(len(list(ast.walk(tree))) <= MAX_NODES, "source has too many nodes")
    _require(_depth(tree) <= MAX_DEPTH, "source nests too deeply")
    found = []
    for stmt in tree.body:
        _require(isinstance(stmt, ast.FunctionDef), "top level must only define functions")
        _plain(stmt.name, "function")
        _require(stmt.name in SIGNATURES, "unexpected function: " + stmt.name)
        _require(stmt.name not in found, "duplicate function: " + stmt.name)
        found.append(stmt.name)
    _require(len(found) == len(FUNCTION_NAMES), "missing: {0}".format(set(FUNCTION_NAMES) - set(found)))
    for stmt in tree.body:
        _function(stmt)


def _load(source):
    """Validate and evaluate the restricted AST; never exec model-generated code."""
    from .bounded_python import load_validated_source
    return load_validated_source(source)


# ------------------------------------------------------------------ oracle
# Independent expectations: these never share code with the candidate path.


def _oracle_eligible(order, policy):
    if order["age_days"] < 0:
        return False
    return order["age_days"] <= policy["window_days"]


def _oracle_refund(order):
    want = order["requested_cents"]
    if want <= 0:
        return 0
    remaining = order["paid_cents"] - order["already_refunded_cents"]
    if remaining < 0:
        return 0
    return want if want < remaining else remaining


def _oracle_key(event):
    return "{0}|{1}".format(event["tenant_id"], event["refund_id"])


def _oracle_inventory(stock, qty, already_applied):
    if already_applied or qty <= 0 or qty > stock:
        return stock
    return stock - qty


# -------------------------------------------------------------------- cases

EVALUATION_PROTOCOL = "blindbench/2.1-boundary-and-retry-coverage"

_SCENARIOS = {
    "eligibility": ("inside", "boundary", "outside", "negative", "age_zero", "age_one"),
    "partial_refund": ("within_balance", "exceeds_remaining", "nonpositive", "fully_refunded", "zero_request"),
    "tenant_retry": ("plain", "ambiguous_split", "long_ids", "near_miss"),
    "inventory_replay": ("apply_ok", "replay", "invalid_qty", "insufficient", "zero_qty"),
}


def _word(rng, size):
    return "".join(rng.choice(_ALPHA) for _ in range(size))


def _bump(text):
    return text[:-1] + ("a" if text[-1] != "a" else "b")


def _case_eligibility(rng, scenario):
    window = rng.choice([7, 14, 30, 45, 60, 90])
    if scenario in ("age_zero", "age_one"):
        age = 0 if scenario == "age_zero" else 1
        cached = max(1, window - rng.randint(1, 3))
    elif scenario == "inside":
        age = rng.randint(2, window - 1)
        cached = age - 1
    elif scenario == "boundary":
        age, cached = window, window - rng.randint(1, 3)
    elif scenario == "outside":
        age = window + rng.randint(1, 20)
        cached = age + rng.randint(1, 10)
    else:
        age, cached = -rng.randint(1, 9), window + rng.randint(0, 5)
    order = {"age_days": age, "cached_window_days": cached}
    policy = {"window_days": window}
    return {"order": order, "policy": policy}, _oracle_eligible(order, policy)


def _case_partial_refund(rng, scenario):
    paid = rng.randint(1000, 90000)
    half = paid // 2
    if scenario == "within_balance":
        done = rng.randint(0, half)
        want = rng.randint(1, paid - done)
    elif scenario == "exceeds_remaining":
        done = rng.randint(1, half)
        want = paid - done + rng.randint(1, 500)
    elif scenario == "nonpositive":
        done, want = rng.randint(0, half), -rng.randint(1, 5000)
    elif scenario == "fully_refunded":
        done, want = paid + rng.choice([0, 0, rng.randint(1, 500)]), rng.randint(1, 9000)
    else:
        done, want = rng.randint(0, half), 0
    order = {"requested_cents": want, "paid_cents": paid, "already_refunded_cents": done}
    return {"order": order}, _oracle_refund(order)


def _event(tenant, refund, attempt, order_id):
    return {"tenant_id": tenant, "refund_id": refund, "attempt_id": attempt, "order_id": order_id}


def _case_tenant_retry(rng, scenario):
    order_id = "ord" + _word(rng, 6)
    tenant, refund = "t" + _word(rng, 5), "rf" + _word(rng, 6)
    other_tenant, other_tenant_refund = "t" + _word(rng, 5), refund
    other_refund = "rf" + _word(rng, 6)
    if scenario == "ambiguous_split":
        tenant, refund = "t" + _word(rng, 3), _word(rng, 5)
        other_tenant, other_tenant_refund = tenant + refund[0], refund[1:]
        other_refund = refund[1:] + _word(rng, 2)
    elif scenario == "long_ids":
        tenant, refund = _word(rng, 30), _word(rng, 30)
        other_tenant, other_tenant_refund, other_refund = _bump(tenant), refund, _bump(refund)
    elif scenario == "near_miss":
        other_tenant, other_tenant_refund, other_refund = _bump(tenant), refund, _bump(refund)
    # Both equal- and unequal-length retries are contractual, not just a1/a2.
    if scenario == "long_ids":
        first_attempt, retry_attempt = _word(rng, 30), _word(rng, 1)
    elif scenario == "plain":
        first_length = rng.randint(1, 29)
        first_attempt = _word(rng, first_length)
        retry_attempt = _word(rng, first_length + 1)
    else:
        first_attempt = _word(rng, 8)
        retry_attempt = _bump(first_attempt)
    events = {
        "base": _event(tenant, refund, first_attempt, order_id),
        "retry": _event(tenant, refund, retry_attempt, order_id),
        "other_refund": _event(tenant, other_refund, first_attempt, order_id),
        "other_tenant": _event(other_tenant, other_tenant_refund, first_attempt, order_id),
    }
    keys = {role: _oracle_key(event) for role, event in events.items()}
    return events, _relations(keys)


def _relations(keys):
    return {
        "retry_matches": keys["retry"] == keys["base"],
        "other_refund_differs": keys["other_refund"] != keys["base"],
        "other_tenant_differs": keys["other_tenant"] != keys["base"],
    }


def _case_inventory_replay(rng, scenario):
    stock = rng.randint(0, 500)
    if scenario in ("apply_ok", "replay"):
        stock = rng.randint(5, 500)
        qty, applied = rng.randint(1, stock), scenario == "replay"
    elif scenario == "invalid_qty":
        qty, applied = -rng.randint(1, 20), False
    elif scenario == "insufficient":
        qty, applied = stock + rng.randint(1, 50), False
    else:
        qty, applied = 0, rng.choice([True, False])
    payload = {"stock": stock, "qty": qty, "already_applied": applied}
    return payload, _oracle_inventory(stock, qty, applied)


_BUILDERS = {
    "eligibility": _case_eligibility,
    "partial_refund": _case_partial_refund,
    "tenant_retry": _case_tenant_retry,
    "inventory_replay": _case_inventory_replay,
}


def _build_cases(seed, count, probe):
    rng = random.Random("blindbench|{0}|{1}|{2}".format(seed, count, probe))
    families = list(PROBES) if probe is None else [probe]
    cases = []
    for family in families:
        scenarios = _SCENARIOS[family]
        for index in range(count // len(families)):
            scenario = scenarios[index % len(scenarios)]
            payload, expected = _BUILDERS[family](rng, scenario)
            cases.append({
                "case_id": "{0}-{1:03d}-{2:04x}".format(family, index, rng.randrange(65536)),
                "family": family, "scenario": scenario, "input": payload, "expected": expected,
            })
    return cases


# --------------------------------------------------------------- evaluation


def _check_seed(seed):
    _require(isinstance(seed, int) and not isinstance(seed, bool), "seed must be an int")
    _require(abs(seed) <= 2**31, "seed out of range")


def _check_count(count):
    _require(isinstance(count, int) and not isinstance(count, bool), "count must be an int")
    _require(count % 4 == 0 and 16 <= count <= 512, "count must be 16..512 and a multiple of 4")


def _run_case(funcs, case):
    """Return (passed, observed); any candidate error is a failed case."""
    family, payload, expected = case["family"], case["input"], case["expected"]
    try:
        if family == "eligibility":
            got = funcs["eligible"](dict(payload["order"]), dict(payload["policy"]))
            if got is not True and got is not False:
                return False, "non-bool result: {0}".format(type(got).__name__)
        elif family == "partial_refund":
            got = funcs["refund_cents"](dict(payload["order"]))
        elif family == "inventory_replay":
            got = funcs["inventory_after"](payload["stock"], payload["qty"], payload["already_applied"])
        else:
            keys = {}
            for role in ("base", "retry", "other_refund", "other_tenant"):
                key = funcs["operation_key"](dict(payload[role]))
                if type(key) is not str or not key:
                    return False, "invalid key for {0}: {1!r}".format(role, key)
                keys[role] = key
            got = _relations(keys)
        if family in ("partial_refund", "inventory_replay") and type(got) is not int:
            return False, "non-int result: {0}".format(type(got).__name__)
        return got == expected, got
    except Exception as exc:
        return False, "error: {0}".format(type(exc).__name__)


def evaluate(source, seed, count=80, probe=None):
    """Score a candidate source on cases freshly generated for this seed."""
    _check_seed(seed)
    _check_count(count)
    _require(probe is None or probe in PROBES, "unknown probe: {0!r}".format(probe))
    funcs = _load(source)
    cases = _build_cases(seed, count, probe)
    by_family = {case["family"]: {"passes": 0, "failures": 0, "total": 0} for case in cases}
    passes, first_failures = 0, []
    for case in cases:
        ok, observed = _run_case(funcs, case)
        tally = by_family[case["family"]]
        tally["total"] += 1
        tally["passes" if ok else "failures"] += 1
        if ok:
            passes += 1
        elif len(first_failures) < 3:
            first_failures.append({
                "case_id": case["case_id"], "family": case["family"],
                "input": deepcopy(case["input"]), "expected": case["expected"], "observed": observed,
            })
    public = [{key: case[key] for key in ("case_id", "family", "input", "expected")} for case in cases]
    return {
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "passed": passes == len(cases), "total": len(cases),
        "passes": passes, "failures": len(cases) - passes,
        "by_family": by_family, "first_failures": first_failures,
        "cases_sha256": _sha(json.dumps(public, sort_keys=True, default=str)),
        "source_sha256": _sha(source),
    }


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def smoke_example(source):
    """One ordinary expired return: a sanity check, never a release gate."""
    order = {"age_days": 45, "cached_window_days": 60}
    policy = {"window_days": 30}
    funcs = _load(source)
    payload = {"order": order, "policy": policy}
    expected = _oracle_eligible(order, policy)
    ok, observed = _run_case(funcs, {"family": "eligibility", "input": payload, "expected": expected})
    return {
        "case_id": "smoke-expired-return", "family": "eligibility", "input": payload,
        "expected": expected, "observed": observed, "passed": ok, "source_sha256": _sha(source),
    }


# ---------------------------------------------------------------- incidents


def make_incident(seed):
    """Build one blind incident. mutation_ids is private benchmark state."""
    _check_seed(seed)
    rng = random.Random("incident|{0}".format(seed))
    variants = {name: "ok" for name in FUNCTION_NAMES}
    mutation_ids = []
    families = rng.sample(PROBES, rng.randint(2, len(PROBES)))
    for family in sorted(families, key=PROBES.index):
        function = _FAMILY_FUNCTION[family]
        variant = rng.choice(sorted(_FAULTS[function]))
        variants[function] = variant
        mutation_ids.append("{0}/{1}".format(family, variant))
    return {
        "incident_id": "inc-" + _sha("incident|{0}".format(seed))[:10],
        "contract": deepcopy(CONTRACT),
        "symptom": SYMPTOM,
        "faulty_source": _compose(variants),
        "mutation_ids": mutation_ids,
    }
