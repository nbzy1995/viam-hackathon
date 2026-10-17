"""Checks at the language-to-physical-action boundary; no robot connection."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

import workshop_text as console
from task_interpreter import validate_task


def test_command_sequence_uses_observed_objects_and_verified_history():
    from task_interpreter import resolve_commands
    scene = {'objects': [{'id': 'carton', 'world_mm': [400, -400, 150], 'movable': True}]}
    plan = {'decision': 'execute', 'message': 'Move and return.', 'grounding': 'Current view and verified history.',
            'commands': [{'action': 'translate', 'object_id': 'carton', 'dx_mm': 30, 'dy_mm': 0},
                         {'action': 'restore', 'object_id': 'carton', 'dx_mm': 0, 'dy_mm': 0}]}
    history = [{'object_id': 'carton', 'before_world_mm': [390, -400, 150],
                'after_world_mm': [400, -400, 150], 'verified': True}]
    resolved = resolve_commands(plan, scene, history)
    assert resolved[0]['target_xy'] == [430, -400]
    assert resolved[1]['target_xy'] == [400, -400]
    # A failed/preview action cannot provide a previous physical position.
    plan['commands'] = [plan['commands'][1]]
    with pytest.raises(ValueError, match='previous'):
        resolve_commands(plan, scene, [history[0] | {'verified': False}])
    plan['commands'][0]['object_id'] = 'invented-object'
    with pytest.raises(ValueError, match='observed'):
        resolve_commands(plan, scene, history)


def test_physical_controller_can_request_overview_but_preview_cannot(monkeypatch, tmp_path):
    # The user-facing regression: an unseen target requests a higher look, not
    # a permanent rejection merely because the carton is absent at home.
    controller = object.__new__(console.TextController)
    controller.robot = None
    controller.arm = SimpleNamespace(stop=AsyncMock())
    controller.execute, controller.busy, controller.scene = True, False, None
    controller.workspace = tmp_path / 'workspace'
    controller.notify = lambda *a, **k: None
    controller.checked = {'frames': {}}
    monkeypatch.setattr(console, 'ROOT', tmp_path)
    monkeypatch.setattr(console, 'validate_setup', AsyncMock())
    observation = AsyncMock(return_value={'objects': [], 'images': [], 'overview_attempted': False})
    monkeypatch.setattr(console, 'capture_scene', observation)
    higher = AsyncMock(return_value={'objects': [], 'images': [], 'overview_attempted': True})
    monkeypatch.setattr(console, 'capture_overview', higher)
    look = {'decision': 'observe', 'commands': [], 'message': 'Need a wider look.', 'grounding': 'Target not visible.'}
    reject = look | {'decision': 'reject', 'message': 'Target absent after the wider look.'}
    monkeypatch.setattr(console, 'interpret', AsyncMock(side_effect=[look, reject]))
    result = asyncio.run(controller.run('Move the red block right slightly.'))
    assert result['outcome'] == 'reject'
    higher.assert_awaited_once()
    controller.execute = False
    higher.reset_mock()
    monkeypatch.setattr(console, 'interpret', AsyncMock(return_value=look))
    result = asyncio.run(controller.run('Move the red block right slightly.'))
    assert result['outcome'] == 'observation_required'
    higher.assert_not_called()


def test_completed_overview_is_passed_back_as_a_completed_action(monkeypatch, tmp_path):
    controller = object.__new__(console.TextController)
    controller.robot = None
    controller.arm = SimpleNamespace(stop=AsyncMock())
    controller.execute, controller.busy, controller.scene = True, False, None
    controller.workspace, controller.checked = tmp_path / 'workspace', {'frames': {}}
    controller.notify = lambda *a, **k: None
    monkeypatch.setattr(console, 'ROOT', tmp_path)
    monkeypatch.setattr(console, 'validate_setup', AsyncMock())
    scene = {'objects': [{'id': 'piece', 'label': 'block'}], 'images': [],
             'camera_available': True, 'overview_attempted': False}
    monkeypatch.setattr(console, 'capture_scene', AsyncMock(return_value=scene))
    higher = AsyncMock(return_value=scene | {'overview_attempted': True})
    monkeypatch.setattr(console, 'capture_overview', higher)
    look = dict(decision='observe', commands=[], message='Look from above.', grounding='Requested higher view.')

    async def interpreter(request, current, *args):
        if not current['overview_attempted']:
            return look
        assert current['completed_actions'] == [dict(action='observe', view='higher',
            camera_available=True, returned_home=True)]
        return look | dict(decision='status', message='The fresh higher view shows a block.')

    monkeypatch.setattr(console, 'interpret', interpreter)
    transfer = AsyncMock()
    monkeypatch.setattr(controller, 'run_tabletop', transfer)
    result = asyncio.run(controller.run('Move higher, and see again.'))
    assert result.get('outcome') == 'status' and result['success'], result.get('error')
    higher.assert_awaited_once()
    transfer.assert_not_called()
    controller.arm.stop.assert_not_called()


def task():
    return dict(decision='execute', message='Move 30 mm along world X.',
                commands=[{'action': 'translate', 'object_id': 'carton', 'dx_mm': 30., 'dy_mm': 0.}],
                grounding='Explicit world X and 30 mm.')


def test_invalid_model_output_cannot_become_motion():
    valid = task()
    assert validate_task(valid) == valid
    for update in ({'dx_mm': float('nan')}, {'dx_mm': float('inf')},
                   {'dx_mm': True}, {'dx_mm': 0}, {'action': 'open_gripper'},
                   {'extra_code': 'run()'}):
        with pytest.raises(ValueError):
            validate_task(valid | {'commands': [valid['commands'][0] | update]})
    for update in ({'decision': 'reject'}, {'grounding': ''}, {'extra': True}):
        with pytest.raises(ValueError):
            validate_task(valid | update)
    assert validate_task(valid | {'decision': 'reject', 'commands': []})['decision'] == 'reject'


def test_long_moves_and_stacking_resolve_without_object_or_distance_allowlists():
    from task_interpreter import resolve_commands
    scene = {'objects': [{'id': 'unknown-shape', 'world_mm': [100, 200, 30], 'movable': False},
                         {'id': 'support', 'world_mm': [250, 300, 60], 'movable': False}]}
    plan = task() | {'commands': [
        {'action': 'translate', 'object_id': 'unknown-shape', 'dx_mm': 150, 'dy_mm': 0},
        {'action': 'place_on', 'object_id': 'unknown-shape', 'target_id': 'support', 'dx_mm': 0, 'dy_mm': 0}]}
    result = resolve_commands(plan, scene, [])
    assert result[0]['target_xy'] == [250, 200]
    assert result[1]['target_xy'] == [250, 300]
    assert result[1]['target_id'] == 'support'


def test_camera_direction_follows_calibrated_rotation():
    # Viam R_y(pi) R_z(pi/2): camera +X is world +Y; +Y is world +X.
    basis = console.camera_directions([100, 40, 150], {'z': 600, 'oZ': -1, 'theta': 90})
    np.testing.assert_allclose(basis['image_right_world_xy_unit'], [0, 1], atol=1e-10)
    np.testing.assert_allclose(basis['image_down_world_xy_unit'], [1, 0], atol=1e-10)


def test_unchanged_or_wrong_direction_carton_cannot_pass():
    before = np.array([400., -400., 150.])
    for displacement in (5., 30., 50.):
        delta = np.array([displacement, 0.])
        for after in (before, before - [displacement, 0, 0]):
            with pytest.raises(RuntimeError, match='Placement error'):
                console.verify_translation(before, after, delta)
        result = console.verify_translation(before, before + [displacement, 0, 0], delta)
        assert result['error_mm'] == 0


def test_rejected_request_never_calls_transfer(monkeypatch, tmp_path):
    controller = object.__new__(console.TextController)
    controller.robot = None
    controller.arm = SimpleNamespace(stop=AsyncMock())
    controller.execute, controller.busy, controller.scene = True, False, None
    controller.workspace = tmp_path / 'workspace'
    controller.notify = lambda *a, **k: None
    controller.checked = {'frames': {}}
    monkeypatch.setattr(console, 'ROOT', tmp_path)
    monkeypatch.setattr(console, 'validate_setup', AsyncMock())
    monkeypatch.setattr(console, 'capture_scene', AsyncMock(return_value={'objects': [], 'images': []}))
    transfer = AsyncMock()
    monkeypatch.setattr(console, 'transfer_object', transfer)
    monkeypatch.setattr(console, 'interpret', AsyncMock(return_value=task() | {'decision': 'reject', 'commands': []}))
    result = asyncio.run(controller.run('Move it over there.'))
    assert result['outcome'] == 'reject' and not result['execution_attempted']
    transfer.assert_not_called()
    controller.arm.stop.assert_not_called()
    controller.busy = True
    result = asyncio.run(controller.run('Another request'))
    assert result['error'] == 'busy'
    transfer.assert_not_called()


@pytest.mark.parametrize('execute', [True, False])
def test_round_trip_intent_calls_existing_routine(monkeypatch,tmp_path,execute):
    controller=object.__new__(console.TextController)
    controller.robot=object();controller.arm=SimpleNamespace(stop=AsyncMock())
    controller.execute,controller.busy,controller.scene=execute,False,object()
    controller.workspace,controller.checked=tmp_path/'workspace',{'frames': {}}
    controller.notify=lambda *a,**k:None
    monkeypatch.setattr(console,'ROOT',tmp_path)
    monkeypatch.setattr(console,'validate_setup',AsyncMock())
    monkeypatch.setattr(controller,'observe',AsyncMock(return_value={'objects':[]}))
    decision={'decision':'roundtrip','commands':[],'message':'Run the carton A to B to A routine.','grounding':'Requested station round trip.'}
    monkeypatch.setattr(console,'interpret',AsyncMock(return_value=decision))
    routine=AsyncMock(return_value={'outcome':'roundtrip_completed' if execute else 'preview_passed',
        'success':execute,'execution_attempted':execute,'verifications':[]})
    monkeypatch.setattr(console,'run_cycle',routine,raising=False)
    result=asyncio.run(controller.run('Move the cartoon to point B and then to A back.'))
    routine.assert_awaited_once_with(controller.robot,controller.scene,controller.checked,execute,notify=controller.notify)
    assert result['success']==execute
    assert result['task']==decision


@pytest.mark.parametrize('description_decision', ['status', 'deliver_bottle'])
def test_scan_describes_fresh_views_without_starting_another_action(monkeypatch, tmp_path, description_decision):
    controller = object.__new__(console.TextController)
    controller.robot, controller.scene = object(), object()
    controller.arm = SimpleNamespace(stop=AsyncMock())
    controller.execute, controller.busy = True, False
    controller.workspace, controller.checked = tmp_path, {'frames': {}}
    controller.notify = lambda *a, **k: None
    monkeypatch.setattr(console, 'ROOT', tmp_path)
    monkeypatch.setattr(console, 'validate_setup', AsyncMock())
    monkeypatch.setattr(controller, 'observe', AsyncMock(return_value={'objects': []}))
    decision = dict(decision='scan_table', commands=[], message='Look around.', grounding='Requested table scan.')
    fresh = {'objects': [], 'images': [{'path': f'view-{i}.jpg'} for i in range(3)],
             'completed_actions': [{'action': 'scan_table', 'image_count': 3, 'returned_home': True}]}
    async def scan(*args):
        args[5]['execution_attempted'] = True
        return fresh
    interpreter = AsyncMock(side_effect=[decision, decision | {'decision': description_decision}])
    monkeypatch.setattr(console, 'scan_table', scan)
    monkeypatch.setattr(console, 'interpret', interpreter)
    move = AsyncMock()
    monkeypatch.setattr(console, 'move_bottle', move)
    result = asyncio.run(controller.run('What do you see on my table?'))
    assert interpreter.await_args_list[1].args[1] == fresh
    assert result['success'] == (description_decision == 'status')
    move.assert_not_called()
    assert controller.arm.stop.await_count == int(description_decision != 'status')


def test_roundtrip_cannot_mix_in_generated_commands():
    decision={'decision':'roundtrip','commands':[],'message':'Run demo.','grounding':'Requested demo.'}
    assert validate_task(decision)==decision
    with pytest.raises(ValueError):
        validate_task(decision|{'commands':[{'action':'translate','object_id':'carton','dx_mm':10,'dy_mm':0}]})
