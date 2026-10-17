"""Negative controls: a permissive grader must not conceal a wrong robot task."""
from copy import deepcopy

from evaluate_text import grade, summarize


def test_grader_rejects_wrong_support_source_order_and_numbers():
    task = {'decision': 'execute', 'message': 'Proposed stack.', 'grounding': 'Measured objects.',
            'commands': [{'action': 'place_on', 'object_id': 'a', 'target_id': 'b', 'dx_mm': 0, 'dy_mm': 0},
                         {'action': 'translate', 'object_id': 'c', 'target_id': None, 'dx_mm': 12, 'dy_mm': -16}]}
    expected = {'decision': task['decision'], 'commands': deepcopy(task['commands'])}
    assert not grade(task, expected)
    for change in ({'target_id': 'c'}, {'object_id': 'c'}, {'dx_mm': 2}, {'dx_mm': float('nan')}):
        wrong = deepcopy(task)
        wrong['commands'][0].update(change)
        assert grade(wrong, expected)
    assert grade(task | {'commands': list(reversed(task['commands']))}, expected)
    assert grade(task | {'commands': task['commands'][:1]}, expected)


def test_grader_checks_real_references_and_leaves_prose_review_pending():
    task = {'decision': 'execute', 'message': 'Restore.', 'grounding': 'Previous move.',
            'commands': [{'action': 'restore', 'object_id': 'a', 'target_id': None, 'dx_mm': 0, 'dy_mm': 0}]}
    assert grade(task, task, {'objects': [{'id': 'a', 'world_mm': [1, 2, 3]}]}, [])
    status = dict(task, decision='status', commands=[])
    assert not grade(status, {'decision': ['reject', 'status'], 'commands': []})
    summary = summarize([{'id': 'facts', 'family': 'status', 'passed': True, 'seconds': 1,
                          'manual_rubric': ['Do not claim the gripper is empty.']}])
    assert summary['manual_review_pending'] == ['facts']
