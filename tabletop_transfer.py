"""Measured tabletop pick/place using native Viam motion and gripper APIs.

No language or object-name allowlist. The depth surface supplies the grasp pose;
the planner checks reach and collisions before any actuator call.
"""
import json
import math
from copy import deepcopy

import numpy as np
from google.protobuf.json_format import MessageToDict
from viam.components.arm import Arm
from viam.components.gripper import Gripper
from viam.proto.common import (Pose, PoseInFrame, Geometry, GeometriesInFrame,
                               RectangularPrism, Vector3, WorldState, Transform)
from viam.proto.service.motion import Constraints, LinearConstraint, CollisionSpecification
from viam.services.motion import MotionClient

from workshop_static import check_arm


class NativePreviewError(RuntimeError):
    """A plan-only failure; physical execution errors never use this type."""


def surface_geometry(points, table_z):
    """Fit a horizontal top and its oriented footprint, retaining fit evidence."""
    p = np.asarray(points)
    p = p[np.isfinite(p).all(axis=1) & (p[:, 2] > table_z + 5)]
    if len(p) < 100:
        raise ValueError('Depth does not resolve an object above the table')
    # Dense depth plane, not the highest tail: stereo edge outliers can sit well
    # above a flat object's true top and shrink the selected patch to one corner.
    lo_z, hi_z = np.percentile(p[:, 2], [2, 98])
    bins = np.arange(lo_z, hi_z + 4.01, 4.)
    if len(bins) < 2: bins = np.array([lo_z - 2, lo_z + 2])
    counts, edges = np.histogram(p[:, 2], bins=bins)
    peak = int(np.argmax(counts))
    top = float((edges[peak] + edges[peak + 1]) / 2)
    surface = p[abs(p[:, 2] - top) <= 5]
    if len(surface) < 100:
        raise ValueError('Depth does not resolve the top surface')
    center = np.median(surface, axis=0)
    _, axes = np.linalg.eigh(np.cov(surface[:, :2].T))
    major = axes[:, -1]
    basis = np.column_stack([major, [-major[1], major[0]]])
    projected = surface[:, :2] @ basis
    lo, hi = np.percentile(projected, [1, 99], axis=0)
    center[:2] = ((lo + hi) / 2) @ basis.T
    length, width = hi - lo
    theta = (180 - math.degrees(math.atan2(major[1], major[0]))) % 180
    theta = min((theta, theta + 180), key=lambda x: abs(x - 163))
    # Nearly round objects have no useful principal-axis orientation.
    if length / max(width, 1) < 1.3:
        theta = 163.
    residual = float(np.percentile(abs(surface[:, 2] - center[2]), 95))
    return {'center_top_world_mm': center.tolist(), 'top_z_mm': float(center[2]),
            'bottom_z_mm': float(table_z), 'length_mm': float(length),
            'width_mm': float(width), 'theta_degrees': theta,
            'surface_residual_mm': residual, 'surface_points': len(surface)}


def table_height(points, modeled_z):
    p = np.asarray(points)
    z = p[np.isfinite(p).all(axis=1), 2]
    # Search around the configured horizontal table, using the dominant depth plane.
    z = z[(z > modeled_z - 30) & (z < modeled_z + 50)]
    if len(z) < 1000:
        raise ValueError('Table plane is not resolved in the depth image')
    counts, bins = np.histogram(z, bins=np.arange(modeled_z - 30, modeled_z + 52, 2))
    peak = int(np.argmax(counts))
    plane = z[(z >= bins[peak] - 2) & (z <= bins[peak + 1] + 2)]
    if len(plane) < 1000:
        raise ValueError('Table plane has insufficient depth support')
    return float(np.median(plane))


def box(label, geom, *, carried=False, tcp_z=0, grasp_theta=None):
    top, bottom = geom['top_z_mm'], geom['bottom_z_mm']
    x, y, _ = geom['center_top_world_mm']
    center = Pose(x=0 if carried else x, y=0 if carried else y,
                  z=tcp_z - (top + bottom) / 2 if carried else (top + bottom) / 2,
                  o_z=1 if carried else -1,
                  theta=(geom['theta_degrees'] - grasp_theta if grasp_theta is not None else 0)
                        if carried else geom['theta_degrees'])
    return Geometry(label=label, center=center, box=RectangularPrism(
        dims_mm=Vector3(x=geom.get('body_length_mm', geom['length_mm']) + 4,
                       y=geom.get('body_width_mm', geom['width_mm']) + 4, z=top - bottom)))


def prepare_transfer(observation, command, history=()):
    objects = {o['id']: o for o in observation['objects']}
    obj = objects[command['object_id']]
    if 'geometry' not in obj:
        raise ValueError(f"{obj['id']}: depth has not resolved a grasp surface")
    geom = dict(obj['geometry'])
    if not 5 < geom['width_mm'] < 75:
        raise ValueError(f"{obj['id']}: measured width {geom['width_mm']:.1f} mm does not fit the gripper opening")
    table_z = observation['table_surface_z_mm']
    prior = next((h for h in reversed(history) if h.get('verified') and h['object_id'] == obj['id']), None)
    if prior and 'after_support_z_mm' in prior and np.linalg.norm(
            np.array(prior['after_world_mm'][:2]) - obj['world_mm'][:2]) < 10:
        expected_top = prior.get('after_top_z_mm')
        if expected_top is not None and abs(expected_top - geom['top_z_mm']) < 10:
            geom['bottom_z_mm'] = prior['after_support_z_mm']
    support_z = table_z
    target_id = command.get('target_id')
    if target_id:
        support = objects[target_id].get('geometry')
        if not support:
            raise ValueError('Target support needs a measured top surface')
        if min(support['length_mm'], support['width_mm']) < 15:
            raise ValueError('Measured support is too narrow to center this placement reliably')
        support_z = support['top_z_mm']
    elif command.get('action') == 'restore' and prior:
        support_z = prior.get('before_support_z_mm', table_z)
    height = geom['top_z_mm'] - geom['bottom_z_mm']
    if height <= 5:
        raise ValueError('Measured object height does not give the fingertips table clearance')
    # The configured gripper fingertips extend 50 mm below its TCP. Place their
    # tips 20 mm below the top (or halfway down a short object), above its support.
    tcp_z = geom.get('grasp_tcp_z_mm', geom['top_z_mm'] + 50 - min(20., height / 2))
    placement_z = tcp_z + support_z - geom['bottom_z_mm'] + 1
    source = list(geom['center_top_world_mm'][:2])
    target = list(command['target_xy'])
    if target_id:
        target = list(objects[target_id]['geometry']['center_top_world_mm'][:2])
    # Start with a local lift above both grasp and release. A tall object elsewhere
    # must not force an otherwise reachable destination onto an unreachable plane.
    # All neighbors remain in every native collision check. Keep the old higher
    # route as a fallback when obstacles block the lower carrying path.
    clearance_z = max(tcp_z, placement_z) + 50
    fallback_z = max(clearance_z, max(o.get('geometry', {}).get('top_z_mm', table_z)
                                    for o in objects.values()) + 100)
    return {'object_id': obj['id'], 'source_xy': source, 'target_xy': target,
            'geometry': geom, 'source_support_z_mm': geom['bottom_z_mm'],
            'target_support_z_mm': support_z, 'target_id': target_id,
            'tcp_grasp_z_mm': tcp_z, 'tcp_place_z_mm': placement_z,
            'clearance_z_mm': clearance_z,
            'fallback_clearance_z_mm': fallback_z,
            'target_top_z_mm': support_z + height + 1}


async def transfer_object(robot, scene, checked, observation, transfer, execute, report, save,
                          *, progress=lambda _: None, before_execute=None):
    # Try several jaw angles that fit the measured footprint. This is grasp
    # search over collision-checked poses, not permission to ignore a neighbor.
    errors = []
    g = transfer['geometry']
    heights = [transfer['clearance_z_mm'], transfer.get('fallback_clearance_z_mm', transfer['clearance_z_mm'])]
    for height in dict.fromkeys(heights):
        for offset in (0, 15, -15, 30, -30, 90, -90):
            width = g['width_mm'] * math.cos(math.radians(offset)) + g['length_mm'] * abs(math.sin(math.radians(offset)))
            if width >= 75: continue
            candidate = transfer | {'grasp_theta_degrees': g['theta_degrees'] + offset, 'clearance_z_mm': height}
            try:
                result = await _transfer_object(robot, scene, checked, observation, candidate, execute,
                                                report, save, progress=progress, before_execute=before_execute)
            except NativePreviewError as exc:
                if not any(word in str(exc).lower()
                        for word in ('constraint', 'collision', 'ik solution', 'no direct solutions')):
                    raise  # Transport/hardware failures do not justify another grasp attempt.
                errors.append({'angle_degrees': candidate['grasp_theta_degrees'],
                               'clearance_z_mm': height, 'reason': str(exc)})
                report['grasp_preview_failures'] = errors
                save()
                continue
            return result
    raise RuntimeError('No complete pick/place route passed native planning: ' + json.dumps(errors))


async def approach_from_grasp(motion, grasp_request, approach_pose, home_joints):
    """Find an approach branch that admits the vertical descent; plans only.

    The unconstrained probe selects a grasp configuration, never an executed
    descent. Reverse planning retains the real descent's linear constraint and
    collision permissions. The entire forward route is then previewed again.
    """
    seed = deepcopy(grasp_request)
    seed['constraints'].pop('linearConstraint', None)
    seed['extra']['start_state'] = {'configuration': {'arm': np.radians(home_joints).tolist()}}
    grasp = await motion.do_command({'plan': json.dumps(seed)}, timeout=15)
    reverse = deepcopy(grasp_request)
    reverse['destination'] = MessageToDict(approach_pose)
    reverse['extra']['start_state'] = {'configuration': {'arm': grasp['plan'][-1]['arm']}}
    approach = await motion.do_command({'plan': json.dumps(reverse)}, timeout=15)
    return np.degrees(approach['plan'][-1]['arm']).tolist()


async def _transfer_object(robot, scene, checked, observation, transfer, execute, report, save,
                          *, progress=lambda _: None, before_execute=None):
    arm, grip = Arm.from_robot(robot, 'arm'), Gripper.from_robot(robot, 'gripper')
    motion = MotionClient.from_robot(robot, 'builtin')
    await check_arm(arm)
    q = np.array((await arm.get_joint_positions(timeout=5)).values)
    if max(abs(q - checked['home_joints'])) > .1:
        raise RuntimeError('Pick/place must start from the checked observation pose')
    if (await grip.is_holding_something(timeout=5)).is_holding_something:
        raise RuntimeError('Pick/place expected an empty gripper')
    g = transfer['geometry']
    def pose(xy, z):
        return PoseInFrame(reference_frame='world', pose=Pose(
            x=xy[0], y=xy[1], z=z, o_z=-1, theta=transfer['grasp_theta_degrees']))
    source, target = transfer['source_xy'], transfer['target_xy']
    high = transfer['clearance_z_mm']
    steps = [('approach', pose(source, high), False, False),
             ('grasp', pose(source, transfer['tcp_grasp_z_mm']), True, False),
             ('lift', pose(source, high), True, True),
             ('carry', pose(target, high), True, True),
             ('place', pose(target, transfer['tcp_place_z_mm']), True, True),
             ('withdraw', pose(target, high), True, False), ('home', None, False, False)]
    oid = transfer['object_id']
    # Every observed neighbor is an obstacle, including the placement support.
    neighbors = [box(o['id'], o['geometry']) for o in observation['objects']
                 if o['id'] != oid and 'geometry' in o]
    record = dict(transfer, previews=[], stages=[])
    report.setdefault('transfers', []).append(record)
    prepared = []
    start = q.copy()
    for name, destination, linear, holding in steps:
        obstacles = list(neighbors)
        # Use the measured tabletop for fingertip clearance; retain all configured walls.
        obstacles.append(Geometry(label='observed-table', center=Pose(z=observation['table_surface_z_mm'] - 20, o_z=1),
            box=RectangularPrism(dims_mm=Vector3(x=3000, y=3000, z=40))))
        world = WorldState(obstacles=[GeometriesInFrame(reference_frame='world', geometries=obstacles)])
        allows = []
        if name in ('approach', 'grasp'):
            world.obstacles[0].geometries.append(box(oid, g))
            allows.append(('gripper', oid))
        elif name in ('withdraw', 'home'):
            placed = dict(g, center_top_world_mm=[*target, transfer['target_top_z_mm']],
                          top_z_mm=transfer['target_top_z_mm'], bottom_z_mm=transfer['target_support_z_mm'] + 1)
            world.obstacles[0].geometries.append(box(oid, placed))
            if name == 'withdraw': allows.append(('gripper', oid))
        if holding:
            world.transforms.append(Transform(reference_frame='held-object',
                pose_in_observer_frame=PoseInFrame(reference_frame='gripper', pose=Pose(o_z=1)),
                physical_object=box('held-object', g, carried=True, tcp_z=transfer['tcp_grasp_z_mm'],
                                    grasp_theta=transfer['grasp_theta_degrees'])))
            allows.append(('gripper', 'held-object'))
            # Only the object's intended support contact is allowed, never arm/table or gripper/support.
            if name == 'lift': allows.append(('held-object', 'observed-table'))
            if name == 'place': allows.append(('held-object', transfer['target_id'] or 'observed-table'))
        constraints = Constraints()
        if linear:
            constraints.linear_constraint.append(LinearConstraint(line_tolerance_mm=2, orientation_tolerance_degs=2))
        if allows:
            constraints.collision_specification.append(CollisionSpecification(allows=[
                CollisionSpecification.AllowedFrameCollisions(frame1=a, frame2=b) for a, b in allows]))
        req = {'name': 'builtin', 'componentName': 'gripper', 'worldState': MessageToDict(world),
               'constraints': MessageToDict(constraints),
               'extra': {'timeout': 5, 'start_state': {'configuration': {'arm': np.radians(start).tolist()}}}}
        goal_joints = (checked['home_joints'] if destination is None else
                       transfer.get('approach_joints') if name == 'approach' else None)
        if goal_joints is not None:
            req['componentName'] = 'arm'
            req['extra']['goal_state'] = {'configuration': {'arm': np.radians(goal_joints).tolist()}}
        else:
            req['destination'] = MessageToDict(destination)
        try:
            plan = await motion.do_command({'plan': json.dumps(req)}, timeout=15)
        except Exception as exc:
            if name == 'grasp' and 'approach_joints' not in transfer and 'no direct solutions' in str(exc).lower():
                try:
                    approach_joints = await approach_from_grasp(motion, req, steps[0][1], q)
                except Exception as seed_error:
                    raise NativePreviewError(f'Native grasp branch preview: {seed_error}') from seed_error
                record['approach_branch_retry'] = True
                save()
                return await _transfer_object(robot, scene, checked, observation,
                    transfer | {'approach_joints': approach_joints}, execute, report, save,
                    progress=progress, before_execute=before_execute)
            raise NativePreviewError(f'Native {name} preview: {exc}') from exc
        if any(w[k] != plan['plan'][0][k] for w in plan['plan'] for k in w if k != 'arm'):
            raise RuntimeError('Preview moves another resource')
        path = np.degrees([w['arm'] for w in plan['plan']])
        if len(path) == 1: path = np.vstack([path, path])
        sweep = scene.sweep(path, .5)
        for boundary, finding in sweep['boundaries'].items():
            required = 50 if boundary.startswith('wall-') else 0
            if finding['clearance_mm'] < required:
                raise RuntimeError(f'{name}: measured model clearance at {boundary} is {finding["clearance_mm"]:.1f} mm')
        record['previews'].append({'stage': name, 'end_joints': path[-1].tolist(), 'sweep': sweep})
        prepared.append((name, destination, world, constraints, holding, goal_joints))
        start = path[-1]
    record['preflight_passed'] = True
    save()
    progress(f'{oid}: all native pick/place previews passed')
    if not execute: return record
    if before_execute: await before_execute()
    if max(abs(np.array((await arm.get_joint_positions(timeout=5)).values) - q)) > .05:
        raise RuntimeError('Arm moved during preview')
    report['execution_attempted'] = True
    save()
    await arm.do_command({'set_speed': 3., 'set_acceleration': 6.}, timeout=5)
    await grip.open(timeout=15)
    for index, (name, destination, world, constraints, holding, goal_joints) in enumerate(prepared):
        await check_arm(arm)
        record['pending'] = name
        save()
        if goal_joints is not None:
            if not await motion.move(component_name='arm', destination=None, world_state=world,
                                     constraints=constraints, timeout=120,
                                     extra={'goal_state': {'configuration': {'arm': np.radians(goal_joints).tolist()}}}):
                raise RuntimeError(f'{name} joint-goal move failed')
        elif not await motion.move(component_name='gripper', destination=destination,
                                   world_state=world, constraints=constraints, timeout=120):
            raise RuntimeError(f'{name} failed')
        await check_arm(arm)
        actual = np.array((await arm.get_joint_positions(timeout=5)).values)
        if max(abs(actual - record['previews'][index]['end_joints'])) > .2:
            raise RuntimeError(f'{name}: endpoint differs from preview')
        if name == 'grasp' and not await grip.grab(timeout=15):
            raise RuntimeError('Gripper did not acquire the object')
        if (holding or name == 'grasp') and not (await grip.is_holding_something(timeout=5)).is_holding_something:
            raise RuntimeError('Grasp was not retained')
        if name == 'place':
            await grip.open(timeout=15)
            if (await grip.is_holding_something(timeout=5)).is_holding_something:
                raise RuntimeError('Release failed')
        record['stages'].append(name)
        record['pending'] = None
        save()
        progress(f'{oid}: {name}')
    return record
