"""Offline joint-sweep check using the live xArm URDF and official STL meshes.

Checks all mesh vertices and configured tool boxes against workcell boundary
planes. This is sampled geometry QA, not controller dynamics or a safety system.
Never connects to Viam or commands hardware.
"""
from pathlib import Path
import argparse
import itertools
import json
import math
import xml.etree.ElementTree as ET
import numpy as np

ROOT = Path(__file__).parent
DATA = ROOT / 'artifacts/diagnosis'


def rotation(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    return np.eye(3) + math.sin(angle) * skew + (1 - math.cos(angle)) * skew @ skew


def matrix(xyz=(0, 0, 0), rpy=(0, 0, 0)):
    result = np.eye(4)
    roll, pitch, yaw = rpy
    result[:3, :3] = rotation([0, 0, 1], yaw) @ rotation([0, 1, 0], pitch) @ rotation([1, 0, 0], roll)
    result[:3, 3] = xyz
    return result


def pose_matrix(pose):
    # Viam RDK v1.12.0 spatialmath/orientationVector.go: ZYZ, including
    # its pole convention. OV is neither Euler angles nor axis-angle.
    normal = np.array([pose.get('oX', 0), pose.get('oY', 0), pose.get('oZ', 1)], dtype=float)
    length = np.linalg.norm(normal)
    if not np.isfinite(length) or length == 0:
        raise ValueError('Invalid orientation vector')
    normal /= length
    longitude = math.atan2(normal[1], normal[0])
    latitude = math.acos(float(np.clip(normal[2], -1, 1)))
    theta = math.radians(pose.get('theta', 0))
    if 1 - abs(normal[2]) <= .0001:
        theta += -longitude if normal[2] > 0 else longitude
    result = matrix([pose.get(k, 0) / 1000 for k in ('x', 'y', 'z')])
    result[:3, :3] = rotation([0, 0, 1], longitude) @ rotation([0, 1, 0], latitude) @ rotation([0, 0, 1], theta)
    return result


def transform(vertices, transform_matrix):
    return vertices @ transform_matrix[:3, :3].T + transform_matrix[:3, 3]


def box_vertices(dims):
    half = np.array([dims[k] for k in ('x', 'y', 'z')]) / 2000
    return np.array(list(itertools.product([-1, 1], repeat=3))) * half


class Scene:
    def __init__(self, state=None, wall_buffer_mm=0):
        self.state = state or json.loads((DATA / 'live-state.json').read_text())
        self.xml = ET.fromstring((DATA / 'arm-kinematics.model').read_text())
        self.frames = {f['referenceFrame']: f for f in self.state['frames']}
        self.meshes = {}
        for link in self.xml.findall('link'):
            for collision in link.findall('collision'):
                mesh = collision.find('geometry/mesh')
                if mesh is None:
                    raise ValueError('Unexpected non-mesh arm collision geometry')
                path = DATA / mesh.attrib['filename'].removeprefix('package://description/')
                data = path.read_bytes()
                count = int.from_bytes(data[80:84], 'little')
                triangles = np.frombuffer(data, dtype=np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attr', '<u2')]), count=count, offset=84)
                vertices = np.unique(triangles['vertices'].reshape(-1, 3), axis=0)
                self.meshes[link.attrib['name']] = transform(vertices, self.origin(collision.find('origin')))
        self.joints = list(self.xml.findall('joint'))
        self.active = [j.attrib['name'] for j in self.joints if j.attrib['type'] != 'fixed']
        self.boundaries = {}
        arm_frame = self.frames['arm']['poseInObserverFrame']
        if arm_frame['referenceFrame'] != 'world':
            raise ValueError('Arm base is not world-parented')
        base = pose_matrix(arm_frame['pose'])[:3, 3]
        for name, axis, side in [('wall-front', 0, -1), ('wall-side', 1, 1), ('table', 2, 1), ('ceiling', 2, -1)]:
            frame = self.frames[name]['poseInObserverFrame']
            if frame['referenceFrame'] != 'world':
                raise ValueError('Boundary is not world-parented')
            tf = pose_matrix(frame['pose'])
            if not np.allclose(tf[:3, :3], np.eye(3)):
                raise ValueError('Boundary is not axis aligned')
            geo = self.state['obstacle_geometries'][name][0]
            corners = transform(box_vertices(geo['box']['dimsMm']), tf @ pose_matrix(geo['center']))
            if name.startswith('wall-'):
                # A wall can be on either side of the base. Use the face toward
                # the base, rather than encoding its direction in its name.
                if corners[:, axis].max() < base[axis]:
                    side = 1
                elif corners[:, axis].min() > base[axis]:
                    side = -1
                else:
                    raise ValueError(f'{name} straddles the arm base; inside face is ambiguous')
            surface = corners[:, axis].max() if side == 1 else corners[:, axis].min()
            surface += side * wall_buffer_mm / 1000 if name.startswith('wall-') else 0
            self.boundaries[name] = (axis, side, surface)

    @staticmethod
    def origin(element):
        if element is None:
            return np.eye(4)
        return matrix([float(v) for v in element.get('xyz', '0 0 0').split()], [float(v) for v in element.get('rpy', '0 0 0').split()])

    def forward(self, degrees):
        angles = dict(zip(self.active, np.radians(degrees), strict=True))
        poses = {'world': pose_matrix(self.frames['arm']['poseInObserverFrame']['pose'])}
        for joint in self.joints:
            parent = joint.find('parent').attrib['link']
            child = joint.find('child').attrib['link']
            relative = self.origin(joint.find('origin'))
            if joint.attrib['type'] != 'fixed':
                axis = [float(v) for v in joint.find('axis').attrib['xyz'].split()]
                r = np.eye(4)
                r[:3, :3] = rotation(axis, angles[joint.attrib['name']])
                relative = relative @ r
            poses[child] = poses[parent] @ relative
        return poses

    def vertices(self, degrees):
        poses = self.forward(degrees)
        result = {name: transform(v, poses[name]) for name, v in self.meshes.items()}
        flange = poses['link_eef']
        for name in ('gripper', 'cam'):
            frame = self.frames[name]
            if frame['poseInObserverFrame']['referenceFrame'] != 'arm':
                raise ValueError('Tool is not attached to the arm flange')
            tf = flange @ pose_matrix(frame['poseInObserverFrame']['pose'])
            geometries = self.state['obstacle_geometries']['gripper'] if name == 'gripper' else [frame['physicalObject']]
            for i, geo in enumerate(geometries):
                result[f'{name}:{geo.get("label", i)}'] = transform(box_vertices(geo['box']['dimsMm']), tf @ pose_matrix(geo['center']))
        return result

    def clearances(self, degrees):
        result = {}
        for name, vertices in self.vertices(degrees).items():
            if name == 'link_base':
                continue  # Fixed mounting base is intentionally attached to table.
            for boundary, (axis, side, surface) in self.boundaries.items():
                distance = np.min(side * (vertices[:, axis] - surface)) * 1000
                if boundary not in result or distance < result[boundary]['clearance_mm']:
                    result[boundary] = {'clearance_mm': float(distance), 'link': name}
        return result

    def sweep(self, waypoints, step_degrees=0.1):
        if len(waypoints) < 2 or step_degrees <= 0:
            raise ValueError('Need at least two joint waypoints and a positive sample step')
        worst = {}
        samples = 0
        for segment, (a, b) in enumerate(zip(waypoints, waypoints[1:])):
            a, b = np.asarray(a), np.asarray(b)
            count = max(1, math.ceil(np.max(abs(b - a)) / step_degrees))
            for fraction in np.linspace(0, 1, count + 1):
                q = a + fraction * (b - a)
                for boundary, finding in self.clearances(q).items():
                    if boundary not in worst or finding['clearance_mm'] < worst[boundary]['clearance_mm']:
                        worst[boundary] = dict(finding, segment=segment, fraction=float(fraction), joints_degrees=q.tolist())
                samples += 1
        return {'samples': samples, 'sample_step_degrees': step_degrees, 'boundaries': worst,
                'model_intersection': any(v['clearance_mm'] < 0 for v in worst.values()),
                'max_joint_change_degrees': float(np.max(np.abs(np.diff(np.asarray(waypoints), axis=0))))}


def main():
    before = json.loads((ROOT / 'artifacts/marker-observation-1.json').read_text())
    after = json.loads((ROOT / 'artifacts/wall-contact-last-observation.json').read_text())
    path = [before['arm_joints']['values'], after['arm_joints']['values']]
    scene = Scene()
    predicted = scene.forward(scene.state['joints']['values'])['link_eef'][:3, 3] * 1000
    measured = np.array([scene.state['pose'][k] for k in ('x', 'y', 'z')])
    error = float(np.linalg.norm(predicted - measured))
    report = {'scope': 'Offline reconstruction between recorded endpoints; actual timed path was not recorded.',
              'forward_kinematics_error_mm': error, 'configured_walls': scene.sweep(path),
              'walls_with_50mm_buffer': Scene(wall_buffer_mm=50).sweep(path),
              'current_pose_with_50mm_buffer': Scene(wall_buffer_mm=50).clearances(scene.state['joints']['values'])}
    (DATA / 'recorded-sweep.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if error > 2:
        raise SystemExit('Model does not match reported flange position within 2 mm.')


if __name__ == '__main__':
    main()
