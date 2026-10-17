"""End-to-end controller integration with native plans and a stateful simulated table.

uv run python evaluate_tabletop.py --run-id development-1
No physical actuator calls. Synthetic sensing/contact, not physics validation.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import tempfile
import time
import xml.etree.ElementTree as ET
from unittest.mock import patch

import numpy as np
from viam.robot.client import RobotClient
from viam.services.motion import MotionClient

import workshop_text
from scene_sweep import Scene
from tabletop_sim import TabletopSim
from task_interpreter import read_history, write_json
from workshop_vision import validate_setup

ROOT = Path(__file__).parent
SOURCES = ['evaluate_tabletop.py', 'tabletop_sim.py', 'workshop_text.py', 'tabletop_transfer.py',
           'task_interpreter.py', 'robot_workspace/INSTRUCTIONS.md', 'config/text-task.schema.json',
           'robot_scene.py', 'workshop_vision.py', 'workshop_static.py', 'scene_sweep.py',
           'config/text-vision-services.json', 'config/tabletop-surface.json', 'pyproject.toml', 'uv.lock',
           'artifacts/roundtrip-checked-setup.json', 'artifacts/diagnosis/live-state.json',
           'artifacts/diagnosis/arm-kinematics.model']


def fingerprints():
    mesh_paths = {str(Path('artifacts/diagnosis') / m.attrib['filename'].removeprefix('package://description/'))
                  for m in ET.parse(ROOT/'artifacts/diagnosis/arm-kinematics.model').iter('mesh')}
    hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(set(SOURCES)|mesh_paths)}
    for package in ('viam-sdk','numpy','pillow'):
        hashes['package:'+package] = importlib.metadata.version(package)
    return hashes


def expand_cases(cases):
    for case in cases:
        variant_turns = [i for i,t in enumerate(case['turns']) if t.get('variants')]
        if not variant_turns:
            yield deepcopy(case)
            continue
        if len(variant_turns) != 1:
            raise ValueError('Only one variant-bearing turn per case is supported')
        index = variant_turns[0]
        for variant in case['turns'][index]['variants']:
            copy = deepcopy(case)
            copy['id'] += '-' + variant['name']
            copy['turns'][index].pop('variants')
            copy['turns'][index]['fault'] = variant['fault']
            yield copy


def position(obj):
    g = obj['geometry']
    return np.array([*g['center_top_world_mm'][:2], g['bottom_z_mm']])


def predicates(expect, before, after, events, table_z):
    errors = []
    for wanted in expect.get('final_positions', []):
        oid = wanted['object_id']
        if oid not in after:
            errors.append(f'{oid}: missing from simulated world')
            continue
        actual = position(after[oid])
        if np.linalg.norm(actual[:2]-wanted['xy_mm']) > wanted.get('tolerance_mm',5):
            errors.append(f'{oid}: wrong final XY {actual[:2].tolist()}')
        if 'bottom_z_mm' in wanted and abs(actual[2]-wanted['bottom_z_mm']) > wanted.get('z_tolerance_mm',3):
            errors.append(f'{oid}: wrong support height {actual[2]}')
        if 'min_source_motion_mm' in expect and np.linalg.norm(actual-position(before[oid])) < expect['min_source_motion_mm']:
            errors.append(f'{oid}: insufficient actual movement')
    for oid in expect.get('preserved_ids', []):
        if oid not in after or np.linalg.norm(position(after[oid])-position(before[oid])) > 2:
            errors.append(f'{oid}: non-target moved')
        elif abs((after[oid]['geometry']['theta_degrees']-before[oid]['geometry']['theta_degrees']+180)%360-180) > 2:
            errors.append(f'{oid}: non-target rotated')
    for relation in expect.get('relations', []):
        oid = relation['object_id']
        if relation['predicate'] == 'distance_delta':
            ref = relation['reference_id']
            initial = np.linalg.norm(position(before[oid])[:2]-position(before[ref])[:2])
            final = np.linalg.norm(position(after[oid])[:2]-position(after[ref])[:2])
            if abs(final-initial-relation['delta_mm']) > relation.get('tolerance_mm',5):
                errors.append(f'{oid}: incorrect distance change')
        elif relation['predicate'] == 'supported_by':
            support_id = relation['support_id']
            height = table_z if support_id == 'table' else after[support_id]['geometry']['top_z_mm']
            if abs(position(after[oid])[2]-height) > relation.get('max_contact_gap_mm',3):
                errors.append(f'{oid}: incorrect support contact')
            if support_id != 'table':
                g = after[support_id]['geometry']
                delta = position(after[oid])[:2]-position(after[support_id])[:2]
                angle = np.radians(180-g['theta_degrees'])
                along = np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]]) @ delta
                if np.any(abs(along) > np.array([g['length_mm'],g['width_mm']])/2):
                    errors.append(f'{oid}: does not overlap support')
        else:
            errors.append('Ungraded relation: '+relation['predicate'])
    return errors


def grade_turn(turn, result, before, after, events, history_before, history_after, joints, holding, checked, table_z):
    expected = turn['expect']
    outcome = 'error' if result.get('error') else result.get('outcome')
    errors = []
    if outcome != expected['outcome']:
        errors.append(f'outcome: expected {expected["outcome"]}, got {outcome}')
    if expected['outcome'] in ('completed','status') and not result.get('success'):
        errors.append('Successful task not reported successful')
    errors += predicates(expected,before,after,events,table_z)
    movement = [e for e in events if e['event'] in ('simulated_move','gripper_open','gripper_grab')]
    policy = expected['actuator_policy']
    if policy == 'none' and movement:
        errors.append('Unexpected actuator calls')
    if policy == 'overview_only' and any(e['event'] != 'simulated_move' or e.get('component')!='arm' for e in movement):
        errors.append('Object actuation during overview-only task')
    if policy == 'run' and (not any(e['event']=='grasp' for e in events) or not any(e['event']=='release' for e in events)):
        errors.append('Task skipped grasp or release')
    if policy == 'stop_after_fault':
        stop = next((i for i,e in enumerate(events) if e['event']=='stop'),None)
        if stop is None or any(e in movement for e in events[stop+1:]):
            errors.append('Missing stop or actuation continued after stop')
        detected = next((i for i,e in enumerate(events) if e['event']=='fault'),None)
        if detected is not None and events[detected].get('stage')=='verification':
            # Slip/occlusion is injected into the world at release; the controller
            # learns about it on the next capture, after its normal retreat.
            detected = next((i for i in range(detected+1,len(events)) if events[i]['event']=='capture'),None)
        if detected is not None and (stop is None or stop<detected or any(e in movement for e in events[detected+1:])):
            errors.append('Actuation continued after observable fault')
    overviews = sum(e['event']=='capture' and bool(e.get('high')) for e in events)
    if overviews > 1 or ('observation_count' in expected and overviews != expected['observation_count']):
        errors.append(f'Unexpected overview count: {overviews}')
    captures = [e for e in events if e['event']=='capture']
    initial_z = next((e.get('camera_z_mm') for e in captures if not e.get('high')),None)
    if any(initial_z is None or e.get('camera_z_mm',float('-inf')) < initial_z+10
           for e in captures if e.get('high')):
        errors.append('Overview was not captured from a higher camera pose')
    if expected.get('arm_home') is not None:
        home = max(abs(np.asarray(joints)-checked['home_joints'])) < .1
        if home != expected['arm_home']: errors.append('Wrong terminal arm state')
    if expected.get('gripper_empty') is not None and (holding is None)!=expected['gripper_empty']:
        errors.append('Wrong terminal gripper state')
    if expected['history_policy']=='unchanged' and history_after!=history_before:
        errors.append('Failure/nonmovement changed verified history')
    if expected['history_policy']=='verified_success_only':
        if history_after[:len(history_before)] != history_before:
            errors.append('Verified history prefix was changed')
        added = history_after[len(history_before):]
        releases = [e for e in events if e['event']=='release']
        if not added or len(added)!=len(releases): errors.append('Verified history count differs from completed releases')
        source_world = before
        for entry,release in zip(added,releases):
            if not entry.get('verified') or entry['object_id']!=release['object_id'] or np.linalg.norm(np.array(entry['after_world_mm'])-release['world_mm'])>3:
                errors.append('History does not match independent released state')
            source = source_world.get(release['object_id'])
            if source is None or 'before_world_mm' not in entry or np.linalg.norm(np.array(entry['before_world_mm'])-source['world_mm'])>3:
                errors.append('History does not match independent source state')
            released = release.get('world',{}).get(release['object_id'])
            for field,obj,key in [('before_support_z_mm',source,'bottom_z_mm'),
                                  ('after_support_z_mm',released,'bottom_z_mm'),
                                  ('after_top_z_mm',released,'top_z_mm')]:
                if field in entry and (obj is None or abs(entry[field]-obj['geometry'][key])>3):
                    errors.append('History height differs from independent world: '+field)
            source_world = release.get('world',source_world)
    if 'verified_move_count' in expected and len(history_after)-len(history_before)!=expected['verified_move_count']:
        errors.append('Unexpected verified move count')
    if expected.get('native_planning_required') and not any(e['event']=='native_plan_attempt' for e in events):
        errors.append('Native planner was not exercised')
    if expected.get('no_success_claim') and (result.get('success') or outcome=='completed'):
        errors.append('False task success')
    category = expected.get('failure_category')
    error = result.get('error','').lower()
    if category=='unreachable' and not any(s in error for s in ('unreachable','too far','ik solution')):
        errors.append('Did not reach the expected native reachability failure')
    if category=='collision' and not any(s in error for s in ('collision','constraint','clearance')):
        errors.append('Did not reach the expected native collision failure')
    if turn.get('fault') and not any(e['event']=='fault' and e.get('stage')==turn['fault']['stage'] for e in events):
        errors.append('Requested fault never fired')
    releases = [e for e in events if e['event']=='release']
    for milestone in expected.get('milestones',[]):
        index = milestone['after_object_release']-1
        if index<0 or index>=len(releases) or 'world' not in releases[index]:
            errors.append('Missing intermediate release world snapshot')
            continue
        criteria = {'final_positions':milestone.get('positions',[]),'relations':milestone.get('relations',[])}
        errors += ['milestone: '+e for e in predicates(criteria,before,releases[index]['world'],events,table_z)]
    known = {'outcome','final_positions','relations','preserved_ids','actuator_policy','history_policy',
             'arm_home','gripper_empty','observation_count','visible_claim_ids','min_source_motion_mm',
             'verified_move_count','native_planning_required','no_success_claim','failure_category','milestones'}
    errors += ['Ungraded expected predicate: '+key for key in set(expected)-known]
    return errors


async def main(args):
    source_hashes = fingerprints()
    replay = getattr(args,'replay_of',None)
    if replay:
        original = json.loads(replay.read_text())
        if (original['suite_sha256'] != hashlib.sha256(args.suite.read_bytes()).hexdigest()
                or original['summary']['run'] != original['expected_runs']):
            raise ValueError('Regression replay requires a completed first run of this exact suite')
    elif 'holdout' in args.suite.name:
        frozen = json.loads(args.freeze.read_text()) if args.freeze else {}
        if frozen.get('source_hashes') != source_hashes:
            raise ValueError('Holdout requires matching frozen source hashes from a passing development run')
        development = json.loads((ROOT/'config/office-e2e-development.json').read_text())
        full_count = len(list(expand_cases(development['cases'])))
        if args.case or frozen.get('fully_passed_development_runs') != full_count:
            raise ValueError('Freeze must certify every development run; holdout must run in full')
        for evidence in frozen.get('evidence',[]):
            if hashlib.sha256((ROOT/evidence['path']).read_bytes()).hexdigest()!=evidence['sha256']:
                raise ValueError('Frozen evidence changed')
        if not frozen.get('manual_reviews_resolved') or len(frozen.get('evidence',[]))<2:
            raise ValueError('Freeze requires passing development evidence and resolved manual reviews')
    suite=json.loads(args.suite.read_text())
    cases=list(expand_cases(suite['cases']))
    if args.case:
        cases=[c for c in cases if args.case in c['id']]
    if not cases: raise ValueError('No matching cases')
    output=ROOT/'artifacts/diagnosis'/f'office-e2e-{args.run_id}.json'
    if output.exists(): raise FileExistsError(f'Keep previous evidence: {output}')
    result={'scope':'End-to-end production controller + real interpreter + native Viam planning; stateful local kinematic execution, synthetic perception/contact. No physical actuator calls.',
        'evaluation_role':'regression_replay' if replay else 'heldout_first_pass' if 'holdout' in args.suite.name else 'development',
        'replay_of':str(replay) if replay else None,
        'source_hashes':source_hashes,'suite':str(args.suite),'suite_sha256':hashlib.sha256(args.suite.read_bytes()).hexdigest(),
        'at':datetime.now(timezone.utc).isoformat(),'expected_runs':len(cases),'runs':[]}
    write_json(output.with_name(output.stem+'-manifest.json'),result|{'cases':cases,'fixtures':suite['fixtures']})
    checked=json.loads((ROOT/'artifacts/roundtrip-checked-setup.json').read_text())
    creds=json.loads((ROOT/'.env.viam.json').read_text())
    options=RobotClient.Options.with_api_key(api_key=creds['api_key'],api_key_id=creds['api_key_id'])
    options.dial_options.force_relay=True;options.dial_options.initial_connection_attempts=1;options.dial_options.initial_connection_attempt_timeout=15
    robot=await asyncio.wait_for(RobotClient.at_address(creds['address'],options),25)
    try:
        await validate_setup(robot,checked)
        planner=MotionClient.from_robot(robot,'builtin').do_command
        geometry=Scene()
        for case in cases:
            fixture=deepcopy(suite['fixtures'][case['fixture']])
            sim=TabletopSim(planner,checked,geometry,fixture)
            record={'id':case['id'],'turns':[]};result['runs'].append(record)
            started=time.perf_counter()
            with tempfile.TemporaryDirectory(prefix='viam-e2e-') as temp:
                workspace=Path(temp)
                (workspace/'INSTRUCTIONS.md').write_bytes((ROOT/'robot_workspace/INSTRUCTIONS.md').read_bytes())
                write_json(workspace/'history.json',fixture.get('verified_history',[]))
                with sim.patches():
                    controller=workshop_text.TextController(robot,execute=True,workspace=workspace,notify=lambda *a,**kw:None)
                    with patch.object(workshop_text,'ROOT',workspace):
                        for turn in case['turns']:
                            sim.faults={turn['fault']['stage']:deepcopy(turn['fault'])} if turn.get('fault') else {}
                            sim.visible_ids_before=turn.get('visible_ids_before')
                            sim.visible_ids_after_overview=turn.get('visible_ids_after_overview')
                            before=deepcopy(sim.objects);old_history=read_history(workspace);offset=len(sim.events)
                            response=await controller.run(turn['request'])
                            after=deepcopy(sim.objects);events=deepcopy(sim.events[offset:]);history=read_history(workspace)
                            errors=grade_turn(turn,response,before,after,events,old_history,history,sim.joints,sim.holding,checked,fixture['table_z_mm'])
                            record['turns'].append(dict(request=turn['request'],expected=turn['expect'],errors=errors,passed=not errors,
                                response=response,before=before,after=after,events=events,history_before=old_history,history_after=history,
                                manual_review_pending=turn['expect'].get('visible_claim_ids',[])))
                            write_json(output,result)
                            if errors: break
            record['automated_passed']=len(record['turns'])==len(case['turns']) and all(t['passed'] for t in record['turns'])
            pending = any(t['manual_review_pending'] for t in record['turns'])
            record['passed']=None if pending and record['automated_passed'] else record['automated_passed']
            record['seconds']=round(time.perf_counter()-started,3)
            result['summary']={'automated_passed':sum(r.get('automated_passed',False) for r in result['runs']),
                'fully_passed':sum(r.get('passed') is True for r in result['runs']),'run':len(result['runs']),'expected':len(cases),
                'manual_review_pending':[r['id'] for r in result['runs'] if any(t['manual_review_pending'] for t in r['turns'])]}
            write_json(output,result)
            print(json.dumps({'id':case['id'],'automated_passed':record['automated_passed'],'passed':record['passed'],'seconds':record['seconds'],'errors':[e for t in record['turns'] for e in t['errors']],
                'controller_error':[t['response'].get('error') for t in record['turns'] if t['response'].get('error')]}),flush=True)
    finally:
        await asyncio.wait_for(robot.close(),5)
    return 0 if len(result['runs'])==len(cases) and all(r['automated_passed'] for r in result['runs']) else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',type=Path,default=ROOT/'config/office-e2e-development.json')
    parser.add_argument('--run-id',default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    parser.add_argument('--case')
    parser.add_argument('--freeze',type=Path)
    parser.add_argument('--replay-of',type=Path,help='Explicitly replay a completed suite; never a fresh heldout score')
    args=parser.parse_args()
    if not args.run_id.replace('-','').replace('_','').isalnum(): raise ValueError('Invalid run ID')
    raise SystemExit(asyncio.run(main(args)))
