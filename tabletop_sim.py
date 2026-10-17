"""Isolated kinematic integration simulator, not contact physics or vision QA.

Only ``planner({'plan': ...})`` may reach Viam. Actuator calls update local state.
Object attachment/release and observations are deliberately synthetic. This module
never receives task commands, expected destinations, or evaluation answers.
"""
from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from google.protobuf.json_format import MessageToDict
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.components.switch import Switch
from viam.proto.common import Pose
from viam.services.motion import MotionClient

from robot_scene import camera_directions
from scene_sweep import pose_matrix, rotation
from tabletop_transfer import box


def normalize_fixture(fixture):
    fixture = deepcopy(fixture)
    fixture.setdefault('table_surface_z_mm', fixture.get('table_z_mm'))
    for obj in fixture['objects']:
        if 'geometry' in obj: continue
        length, width, height = obj['size_xyz_mm']
        bottom = obj.get('bottom_z_mm', fixture['table_surface_z_mm'])
        theta = (180 - obj.get('yaw_deg', 0)) % 180
        theta = min((theta, theta + 180), key=lambda t: abs(t - 163))
        top = [*obj['center_xy_mm'], bottom + height]
        obj['world_mm'] = top
        obj['geometry'] = dict(center_top_world_mm=top, top_z_mm=bottom + height,
            bottom_z_mm=bottom, length_mm=length, width_mm=width, theta_degrees=theta,
            surface_points=1000, surface_residual_mm=0)
    return fixture


def matrix_pose(matrix):
    """Inverse of the independently implemented Viam orientation-vector matrix."""
    normal = matrix[:3, 2].copy()
    if abs(normal[2]) > 1 - 1e-10:
        normal[:2] = 0
    longitude = math.atan2(normal[1], normal[0])
    latitude = math.acos(float(np.clip(normal[2], -1, 1)))
    basis = rotation([0, 0, 1], longitude) @ rotation([0, 1, 0], latitude)
    residual = basis.T @ matrix[:3, :3]
    theta = math.atan2(residual[1, 0], residual[0, 0])
    if 1 - abs(normal[2]) <= .0001:
        theta += longitude if normal[2] > 0 else -longitude
    return dict(zip(('x', 'y', 'z'), matrix[:3, 3] * 1000)) | {
        'oX': float(normal[0]), 'oY': float(normal[1]), 'oZ': float(normal[2]),
        'theta': math.degrees(theta)}


class TabletopSim:
    def __init__(self, planner, checked, geometry_scene, fixture, faults=None):
        self.planner, self.checked, self.geometry = planner, checked, geometry_scene
        self.fixture, self.faults = normalize_fixture(fixture), dict(faults or {})
        self.objects = {o['id']: deepcopy(o) for o in self.fixture['objects']}
        self.joints = np.asarray(checked['home_joints'], dtype=float).copy()
        self.holding, self.attachment = None, None
        self.events, self.plan_cache = [], {}
        self.captures = self.releases = 0
        self.overview_seen = False
        self.visible_ids_before = self.visible_ids_after_overview = None
        self.hidden_released = set()
        self._fault_counts, self._fault_signature = {}, None
        self._camera_failed = False
        self.arm, self.gripper, self.motion = _Arm(self), _Gripper(self), _Motion(self)

    def fault(self, stage):
        signature = json.dumps(self.faults, sort_keys=True)
        if signature != self._fault_signature:
            self._fault_counts, self._fault_signature = {}, signature
        fault = self.faults.get(stage)
        if not fault: return None
        self._fault_counts[stage] = self._fault_counts.get(stage, 0) + 1
        occurrence = fault.get('occurrence', 1) if isinstance(fault, dict) else 1
        if self._fault_counts[stage] != occurrence: return None
        self.events.append({'event': 'fault', 'stage': stage})
        return fault

    def frame_matrix(self, name):
        flange = self.geometry.forward(self.joints)['link_eef']
        if name == 'arm':
            return flange
        frame = self.checked['frames'][name]['poseInObserverFrame']
        if frame['referenceFrame'] != 'arm':
            raise RuntimeError('Simulator only supports arm-attached tool/camera frames')
        return flange @ pose_matrix(frame['pose'])

    def set_joints(self, joints):
        self.joints = np.asarray(joints, dtype=float).copy()
        if self.holding:
            obj = self.objects[self.holding]
            g = obj['geometry']
            height = g['top_z_mm'] - g['bottom_z_mm']
            top = (self.frame_matrix('gripper') @ self.attachment)[:3] * 1000
            g.update(center_top_world_mm=top.tolist(), top_z_mm=float(top[2]),
                     bottom_z_mm=float(top[2] - height))
            obj['world_mm'] = top.tolist()

    async def native_plan(self, command, **kwargs):
        if set(command) != {'plan'} or not isinstance(command['plan'], str):
            raise RuntimeError('Simulation boundary permits only native plan requests')
        req = json.loads(command['plan'])
        if set(req) - {'name', 'componentName', 'destination', 'worldState', 'constraints', 'extra'}:
            raise RuntimeError('Unknown native planning request fields')
        if req.get('componentName') not in ('arm', 'gripper'):
            raise RuntimeError('Simulation planner only accepts the isolated arm/tool')
        if set(req.get('extra', {})) - {'timeout', 'start_state', 'goal_state'}:
            raise RuntimeError('Unknown native planning extra fields')
        self.events.append({'event': 'native_plan_attempt'})
        if self.fault('planning'):
            raise RuntimeError('Injected native planning transport failure')
        req.setdefault('extra', {}).setdefault('start_state', {
            'configuration': {'arm': np.radians(self.joints).tolist()}})
        self.add_obstacles(req)
        key = self.plan_key(req)
        # Real previews remain live. Cache only lets execution apply the exact
        # already-checked route rather than introducing a different IK solution.
        result = await self.planner({'plan': json.dumps(req)}, timeout=kwargs.get('timeout', 15))
        if not result.get('plan') or any('arm' not in p for p in result['plan']):
            raise RuntimeError('Native planner returned no arm path')
        if any(p[k] != result['plan'][0][k] for p in result['plan'] for k in p if k != 'arm'):
            raise RuntimeError('Native plan moves another resource')
        self.plan_cache[key] = deepcopy(result)
        self.events.append({'event': 'native_plan', 'waypoints': len(result['plan'])})
        return result

    @staticmethod
    def plan_key(req):
        canonical = deepcopy(req)
        canonical.setdefault('extra', {}).pop('timeout', None)
        for key in ('worldState', 'constraints'):
            if not canonical.get(key):
                canonical.pop(key, None)
        def stable(value):
            if isinstance(value, float): return round(value, 10)
            if isinstance(value, dict): return {k: stable(v) for k, v in value.items()}
            if isinstance(value, list): return [stable(v) for v in value]
            return value
        return json.dumps(stable(canonical), sort_keys=True)

    def add_obstacles(self, req):
        extras = []
        for obstacle in self.fixture.get('extra_obstacles', []):
            x, y, z = obstacle['center_xyz_mm']
            length, width, height = obstacle['size_xyz_mm']
            extras.append({'label': obstacle['id'], 'center': {'x': x, 'y': y, 'z': z,
                'oZ': 1, 'theta': obstacle.get('yaw_deg', 0)},
                'box': {'dimsMm': {'x': length, 'y': width, 'z': height}}})
        visible = self.visible_ids_after_overview if self.overview_seen else self.visible_ids_before
        if visible is not None:
            extras.extend(MessageToDict(box(o['id'], o['geometry'])) for o in self.objects.values()
                          if o['id'] not in visible and o['id'] != self.holding)
        if extras:
            groups = req.setdefault('worldState', {}).setdefault('obstacles', [])
            labels = {g.get('label') for group in groups for g in group.get('geometries', [])}
            extras = [g for g in extras if g['label'] not in labels]
            if extras: groups.append({'referenceFrame': 'world', 'geometries': extras})

    def scene_snapshot(self, high=False):
        # Match the production observation boundary. Static fixture obstacles
        # belong to native planning, not synthetic detections or model input.
        scene = {'table_surface_z_mm': self.fixture['table_surface_z_mm'],
                 'default_view': 'wrist camera', 'robot_base_world_mm': [0, 0, 0]}
        failed = self._camera_failed
        if high and not failed:
            self.overview_seen = True
        hidden = self.faults.get('hidden_until_overview') and not self.overview_seen
        visible = self.visible_ids_after_overview if self.overview_seen else self.visible_ids_before
        objects = [deepcopy(o) for o in self.objects.values()
                   if (visible is None or o['id'] in visible) and o['id'] not in self.hidden_released]
        scene.update(objects=[] if failed or hidden else objects,
                     images=[], overview_attempted=high, camera_available=not bool(failed),
                     errors={'wrist': 'Injected synthetic camera failure'} if failed else {},
                     synthetic_perception=True,
                     captured_at=datetime.now(timezone.utc).isoformat())
        camera = matrix_pose(self.frame_matrix('cam'))
        scene['camera_world_pose'] = camera
        for obj in scene['objects']:
            if 'image_right_xy' in self.fixture and 'image_up_xy' in self.fixture:
                obj['view_directions'] = {
                    'image_right_world_xy_unit': self.fixture['image_right_xy'],
                    'image_down_world_xy_unit': [-v for v in self.fixture['image_up_xy']]}
            else:
                obj['view_directions'] = camera_directions(obj['world_mm'], camera)
        return scene

    async def capture_scene(self, robot, checked, workspace, *, high=False, table_z=None):
        self.captures += 1
        self._camera_failed = bool(self.fault('overview_camera' if high else 'camera'))
        if (any(e['event'] == 'native_plan' for e in self.events)
                and not any(e['event'] == 'simulated_move' for e in self.events)):
            fault = self.fault('before_execution_observation')
            if fault:
                oid = fault.get('object_id', next(iter(self.objects)))
                obj = self.objects[oid]
                delta = np.r_[fault.get('offset_xy_mm', [20, 0]), 0]
                top = (np.asarray(obj['world_mm']) + delta).tolist()
                obj['world_mm'] = top
                obj['geometry']['center_top_world_mm'] = top
        scene = self.scene_snapshot(high)
        self.events.append({'event': 'capture', 'high': high, 'objects': len(scene['objects']),
                            'camera_available': scene['camera_available'],
                            'camera_z_mm': scene['camera_world_pose']['z'],
                            'joints': self.joints.tolist()})
        return scene

    @contextmanager
    def patches(self):
        """Process-local test scope. Do not run concurrently with physical control."""
        def handle(resource, expected):
            def get(robot, name):
                if name != expected:
                    raise RuntimeError(f'Unconfigured simulated resource: {name}')
                return resource
            return get
        def switch(robot, name):
            if name not in self.checked['poses']:
                raise RuntimeError(f'Unconfigured simulated switch: {name}')
            return _Switch(self, name)
        with ExitStack() as stack:
            for owner, name, replacement in (
                (Arm, 'from_robot', handle(self.arm, 'arm')),
                (Gripper, 'from_robot', handle(self.gripper, 'gripper')),
                (MotionClient, 'from_robot', handle(self.motion, 'builtin')),
                (Switch, 'from_robot', switch),
            ):
                stack.enter_context(patch.object(owner, name, replacement))
            stack.enter_context(patch('workshop_text.capture_scene', self.capture_scene))
            stack.enter_context(patch('robot_scene.capture_scene', self.capture_scene))
            yield self


class _Arm:
    def __init__(self, sim): self.sim = sim
    async def get_joint_positions(self, **kwargs):
        return SimpleNamespace(values=self.sim.joints.tolist())
    async def is_moving(self, **kwargs): return False
    async def stop(self, **kwargs): self.sim.events.append({'event': 'stop'})
    async def do_command(self, command, **kwargs):
        if command == {'get_error': True}: return {'error info': [0, 0]}
        if set(command) <= {'set_speed', 'set_acceleration'}:
            return {}
        raise RuntimeError('Unsupported simulated arm command')
    async def get_end_position(self, **kwargs):
        p = matrix_pose(self.sim.frame_matrix('arm'))
        return Pose(x=p['x'], y=p['y'], z=p['z'], o_x=p['oX'], o_y=p['oY'], o_z=p['oZ'], theta=p['theta'])


class _Motion:
    def __init__(self, sim): self.sim = sim
    async def do_command(self, command, **kwargs):
        return await self.sim.native_plan(command, **kwargs)
    async def move(self, *, component_name, destination, world_state=None, constraints=None, extra=None, **kwargs):
        req = {'name': 'builtin', 'componentName': component_name, 'extra': deepcopy(extra or {})}
        req['extra']['start_state'] = {'configuration': {'arm': np.radians(self.sim.joints).tolist()}}
        for name, value in (('destination', destination), ('worldState', world_state), ('constraints', constraints)):
            if value is not None: req[name] = MessageToDict(value)
        self.sim.add_obstacles(req)
        result = self.sim.plan_cache.get(self.sim.plan_key(req))
        if result is None:
            result = await self.sim.native_plan({'plan': json.dumps(req)})
        for waypoint in result['plan']:
            self.sim.set_joints(np.degrees(waypoint['arm']))
        self.sim.events.append({'event': 'simulated_move', 'component': component_name,
                                'joint_endpoint': self.sim.joints.tolist(), 'holding': self.sim.holding})
        return True


class _Gripper:
    def __init__(self, sim): self.sim = sim
    async def is_holding_something(self, **kwargs):
        return SimpleNamespace(is_holding_something=self.sim.holding is not None)
    async def grab(self, **kwargs):
        sim = self.sim
        sim.events.append({'event': 'gripper_grab'})
        if sim.fault('grasp'):
            sim.events.append({'event': 'grasp_failed', 'injected': True})
            return False
        tcp = sim.frame_matrix('gripper')
        point, pose = tcp[:3, 3] * 1000, matrix_pose(tcp)
        for oid, obj in sim.objects.items():
            g = obj['geometry']
            center = np.asarray(g['center_top_world_mm'])
            angle = math.radians((pose['theta'] - g['theta_degrees']) % 180)
            span = abs(g['width_mm'] * math.cos(angle)) + abs(g['length_mm'] * math.sin(angle))
            tip_z = point[2] - 50
            if (np.linalg.norm(point[:2] - center[:2]) <= min(g['width_mm'], g['length_mm']) / 2
                    and g['bottom_z_mm'] < tip_z < g['top_z_mm'] and span < 75):
                sim.holding = oid
                sim.attachment = np.linalg.inv(tcp) @ np.r_[center / 1000, 1]
                sim.events.append({'event': 'grasp', 'object_id': oid, 'tcp_world_mm': point.tolist()})
                return True
        sim.events.append({'event': 'grasp_failed', 'tcp_world_mm': point.tolist()})
        return False
    async def open(self, **kwargs):
        sim = self.sim
        sim.events.append({'event': 'gripper_open', 'holding': sim.holding})
        if not sim.holding: return
        release_fault = sim.fault('release')
        if release_fault:
            sim.events.append({'event': 'release_failed', 'injected': True})
            if isinstance(release_fault, dict) and release_fault.get('kind') == 'rpc_error':
                raise RuntimeError('Injected release RPC error')
            return
        obj = sim.objects[sim.holding]
        g = obj['geometry']
        top = np.asarray(g['center_top_world_mm'])
        height = g['top_z_mm'] - g['bottom_z_mm']
        support = sim.fixture['table_surface_z_mm']
        for other in sim.objects.values():
            if other['id'] == sim.holding: continue
            h = other['geometry']
            delta = top[:2] - np.asarray(h['center_top_world_mm'][:2])
            angle = math.radians(180 - h['theta_degrees'])
            along = np.array([[math.cos(angle), math.sin(angle)], [-math.sin(angle), math.cos(angle)]]) @ delta
            if (abs(along[0]) <= h['length_mm'] / 2 and abs(along[1]) <= h['width_mm'] / 2
                    and h['top_z_mm'] <= g['bottom_z_mm'] + 5):
                support = max(support, h['top_z_mm'])
        top[2] = support + height
        fault = sim.fault('verification')
        if fault:
            if isinstance(fault, dict) and fault.get('kind') == 'hide_released_object':
                sim.hidden_released.add(sim.holding)
            else:
                offset = fault.get('offset_xy_mm', [25, 0]) if isinstance(fault, dict) else [25, 0]
                top[:2] += offset  # Actual simulated slip, not a changed expected result.
        g.update(center_top_world_mm=top.tolist(), top_z_mm=float(top[2]), bottom_z_mm=support)
        obj['world_mm'] = top.tolist()
        sim.events.append({'event': 'release', 'object_id': sim.holding, 'world_mm': top.tolist(),
                           'world': deepcopy(sim.objects)})
        sim.holding, sim.attachment = None, None
        sim.releases += 1


class _Switch:
    def __init__(self, sim, name): self.sim, self.name = sim, name
    async def do_command(self, command, **kwargs):
        if command != {'cfg': True}: raise RuntimeError('Unsupported simulated switch command')
        return {'as_json': json.dumps(self.sim.checked['poses'][self.name])}
    async def set_position(self, position, **kwargs):
        if self.name != 'home-pose' or position != 2:
            raise RuntimeError('Only the checked home switch is supported in simulation')
        return await self.sim.motion.move(component_name='arm', destination=None,
            extra={'goal_state': {'configuration': {'arm': np.radians(self.sim.checked['home_joints']).tolist()}}})
