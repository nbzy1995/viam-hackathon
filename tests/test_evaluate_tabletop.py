from copy import deepcopy
import json
from pathlib import Path
import numpy as np

from evaluate_tabletop import grade_turn
from tabletop_sim import normalize_fixture

ROOT = Path(__file__).resolve().parents[1]


def example():
    suite = json.loads((ROOT/'config/office-e2e-development.json').read_text())
    turn = next(c for c in suite['cases'] if c['id']=='D03_slight_shift')['turns'][0]
    fixture = normalize_fixture(suite['fixtures']['standard'])
    before = {o['id']: o for o in fixture['objects']}
    after = deepcopy(before)
    after['red-1']['geometry']['center_top_world_mm'][1] -= 20
    after['red-1']['world_mm'] = after['red-1']['geometry']['center_top_world_mm'].copy()
    release = dict(event='release',object_id='red-1',world_mm=after['red-1']['world_mm'])
    history = [dict(verified=True,object_id='red-1',before_world_mm=before['red-1']['world_mm'],after_world_mm=release['world_mm'])]
    checked = {'home_joints': [0]*6}
    return turn, dict(success=True,outcome='completed'),before,after,[dict(event='grasp'),release],[],history,[0]*6,None,checked,fixture['table_z_mm']


def test_outcome_grader_catches_noop_wrong_direction_and_collateral_motion():
    args = example()
    assert grade_turn(*args) == []
    for delta in (0,20):
        wrong = deepcopy(args[2])
        wrong['red-1']['geometry']['center_top_world_mm'][1] += delta
        assert any('wrong final XY' in e for e in grade_turn(*args[:3],wrong,*args[4:]))
    wrong = deepcopy(args[3])
    wrong['yellow-1']['geometry']['center_top_world_mm'][0] += 10
    assert any('non-target' in e for e in grade_turn(*args[:3],wrong,*args[4:]))


def test_negative_case_cannot_pass_an_unreached_fault_or_fake_success():
    args = list(example())
    args[0] = deepcopy(args[0])
    args[0]['fault'] = dict(stage='grasp',kind='empty_grasp')
    args[0]['expect'].update(outcome='error',actuator_policy='stop_after_fault',history_policy='unchanged',
                              final_positions=[],preserved_ids=list(args[2]),arm_home=None,gripper_empty=True)
    args[1] = {'success':False,'error':'An unrelated earlier failure'}
    args[3] = deepcopy(args[2]); args[4] = [{'event':'stop'}]; args[6] = []
    assert 'Requested fault never fired' in grade_turn(*args)
    args[4].insert(0,{'event':'fault','stage':'grasp'})
    assert grade_turn(*args) == []
    args[4].append({'event':'gripper_open'})
    assert any('continued after stop' in e for e in grade_turn(*args))


def test_preview_or_invented_history_is_not_completed_motion():
    args = list(example())
    args[1] = {'success':False,'outcome':'preview_passed'}
    assert any('outcome' in e for e in grade_turn(*args))
    args = list(example()); args[6] = deepcopy(args[6]);args[6][0]['after_world_mm'][0]+=100
    assert any('History does not match' in e for e in grade_turn(*args))


def test_history_prefix_and_source_are_independently_checked():
    args = list(example())
    previous = deepcopy(args[6][0])
    args[5] = [previous]
    args[6] = [deepcopy(previous), *deepcopy(args[6])]
    assert grade_turn(*args) == []
    args[6][0]['before_world_mm'][0] += 99
    assert any('history prefix' in e for e in grade_turn(*args))
    args = list(example()); args[6] = deepcopy(args[6])
    args[6][0]['before_world_mm'][0] += 99
    assert any('source state' in e for e in grade_turn(*args))


def test_overview_flag_without_higher_camera_pose_fails():
    args = list(example()); args[0] = deepcopy(args[0])
    args[0]['expect']['observation_count'] = 1
    args[4] += [dict(event='capture',high=False,camera_z_mm=200),
                dict(event='capture',high=True,camera_z_mm=200)]
    assert any('higher camera pose' in e for e in grade_turn(*args))
    args[4][-1]['camera_z_mm'] = 350
    assert grade_turn(*args) == []


def test_intermediate_milestone_cannot_pass_only_final_destination():
    args = list(example()); args[0] = deepcopy(args[0])
    args[0]['expect']['milestones'] = [dict(after_object_release=1,positions=[dict(object_id='red-1',xy_mm=[430,-400])])]
    args[4][-1]['world'] = args[3]
    assert any('milestone:' in e for e in grade_turn(*args))


def test_synchronous_fault_then_motion_then_stop_fails():
    args = list(example()); args[0] = deepcopy(args[0])
    args[0]['expect']['actuator_policy'] = 'stop_after_fault'
    args[4] += [dict(event='fault',stage='grasp'),dict(event='simulated_move'),dict(event='stop')]
    assert any('observable fault' in e for e in grade_turn(*args))


def test_history_support_height_cannot_corrupt_a_later_restore():
    args = list(example()); args[6] = deepcopy(args[6])
    args[6][0]['before_support_z_mm'] = 999
    assert any('History height' in e for e in grade_turn(*args))
