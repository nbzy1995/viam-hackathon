"""Check persistent delivery/return semantics without a physical robot."""
import asyncio
import json
from unittest.mock import AsyncMock

import numpy as np
import pytest
import table_demo as demo


def fixture(monkeypatch, tmp_path, *, failure=None):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'object_id': 'carton', 'spoken_name': 'blue water bottle',
        'delivery_world_xy_mm': [475.9, -241.7], 'location_mode': 'predefined marker'}))
    monkeypatch.setattr(demo, 'CONFIG', config)
    physical = {'cap': np.array([471., -509., 150.]), 'targets': []}

    async def observe(*args):
        return physical['cap'].copy(), 'A' if physical['cap'][1] < -400 else 'B', np.zeros(6)

    async def transfer(robot, geometry, checked, execute, report, save, cap, source, q, dest, **kw):
        assert kw['via_b']
        if not execute:
            return
        await kw['before_execute']()
        report['execution_attempted'] = True
        if failure:
            raise failure
        physical['targets'].append(kw['destination_xy'])
        physical['cap'] = np.array([*kw['destination_xy'], 150.])

    monkeypatch.setattr(demo, 'observe_carton', observe)
    monkeypatch.setattr(demo, 'transfer_carton', transfer)
    return physical


def run(tmp_path, action, execute=True):
    report = dict(success=False, execution_attempted=False, transfers=[])
    asyncio.run(demo.move_bottle(action, None, None, {'frames': {}}, tmp_path, execute,
                                report, lambda: None, lambda message: None))
    return report


def test_delivery_return_remembers_actual_origin_across_requests(monkeypatch, tmp_path):
    physical = fixture(monkeypatch, tmp_path)
    origin = physical['cap'].copy()
    assert run(tmp_path, 'deliver_bottle')['outcome'] == 'bottle_delivered'
    assert demo.context(tmp_path, {'frames': {}})['has_verified_return_position']
    assert run(tmp_path, 'return_bottle')['outcome'] == 'bottle_returned'
    np.testing.assert_allclose(physical['cap'], origin)
    assert physical['targets'] == [[475.9, -241.7], origin[:2].tolist()]
    # A repeated return acknowledges the existing placement without moving again.
    assert run(tmp_path, 'return_bottle')['success']
    assert len(physical['targets']) == 2


def test_preview_does_not_save_a_physical_origin(monkeypatch, tmp_path):
    fixture(monkeypatch, tmp_path)
    result = run(tmp_path, 'deliver_bottle', execute=False)
    assert result['outcome'] == 'preview_passed' and not result['success']
    assert not (tmp_path / 'table-demo-state.json').exists()


@pytest.mark.parametrize('failure', [RuntimeError('Grasp failed'), asyncio.CancelledError()])
def test_interrupted_delivery_preserves_origin_without_verified_return(monkeypatch, tmp_path, failure):
    fixture(monkeypatch, tmp_path, failure=failure)
    with pytest.raises(type(failure)):
        run(tmp_path, 'deliver_bottle')
    state = json.loads((tmp_path / 'table-demo-state.json').read_text())
    assert state['original_world_mm'] == [471., -509., 150.]
    assert state['phase'] == 'delivering'
    with pytest.raises(demo.DemoUnavailable, match='interrupted'):
        run(tmp_path, 'return_bottle')


def test_return_without_delivery_never_calls_motion(monkeypatch, tmp_path):
    fixture(monkeypatch, tmp_path)
    transfer = AsyncMock()
    monkeypatch.setattr(demo, 'transfer_carton', transfer)
    with pytest.raises(demo.DemoUnavailable, match='verified delivery'):
        run(tmp_path, 'return_bottle')
    transfer.assert_not_called()


def test_wrong_placement_does_not_become_verified_delivery(monkeypatch, tmp_path):
    fixture(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match='placement'):
        demo.verify_at(np.array([471., -509., 150.]), [475.9, -241.7])
