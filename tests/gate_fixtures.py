"""Explicit offline event fixtures, never evidence of real model calls."""
from neatrescue import blindbench


def record(case, decision):
    if decision['action'] == 'submit_patch':
        case.journal.emit('blind_model_decision', {'decision': decision,
            'provenance': 'OFFLINE_UNIT_TEST_FIXTURE_NOT_MODEL_CALL'})
    result = case.execute(decision)
    case.journal.emit('blind_tool_result', {'action': decision['action'], 'result': result,
        'provenance': 'OFFLINE_UNIT_TEST_FIXTURE'})
    return result


def prepare(case):
    case.inspected = True
    context = {'source': case.current, 'repository_context_source': 'Entire graph',
               'context': {'OFFLINE_FIXTURE': True}}
    case.journal.save('entire_blind_target_context.json', context)
    case.journal.emit('blind_tool_result', {'action': 'inspect_source', 'result': context,
        'provenance': 'OFFLINE_UNIT_TEST_FIXTURE_NOT_ENTIRE_CALL'})
    record(case, {'action': 'probe', 'probe': 'eligibility'})
    record(case, {'action': 'challenge_incoming'})


def verified(case):
    prepare(case)
    record(case, {'action': 'submit_patch', 'source': blindbench.reference_source()})
    result = record(case, {'action': 'test_patch'})
    assert result['passed']
    return result
