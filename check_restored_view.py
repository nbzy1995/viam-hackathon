"""Offline check of the saved restored-pose RGB-D observation. No robot calls.

The regions below were identified in restored-view-color.png. This is a
diagnostic for that capture, not an automatic calibration or grasp detector.
"""
import json
from pathlib import Path

import numpy as np

from diagnose_depth import fit_plane
from scene_sweep import Scene, pose_matrix

ROOT = Path(__file__).parent


def main():
    observation = json.loads((ROOT / 'artifacts/restored-view-observation.json').read_text())
    depth = np.load(ROOT / 'artifacts/restored-view-depth.npy')
    state = json.loads((ROOT / 'artifacts/diagnosis/manually-restored-state.json').read_text())
    scene = Scene(state=state)
    intr = observation['camera_properties']['intrinsicParameters']
    # White tabletop, excluding the carton, base, walls, and both tape markers.
    v, u = np.mgrid[50:600:4, 240:580:4]
    z = depth[v, u]
    valid = (z > 100) & (z < 1500)
    u, v, z = u[valid], v[valid], z[valid]
    points = np.column_stack(((u-intr['centerXPx'])*z/intr['focalXPx'],
                              (v-intr['centerYPx'])*z/intr['focalYPx'], z))
    plane = fit_plane(points, tolerance_mm=10)
    flange = scene.forward(observation['arm_joints']['values'])['link_eef']
    report = {
        'captured_at': observation['captured_at'],
        'robot_commands': False,
        'calibration_verified': False,
        'table_roi_uv': [240, 50, 580, 600],
        'table_plane_camera_mm': plane,
        'table_model_top_z_mm': scene.boundaries['table'][2] * 1000,
        'hypotheses': {},
        'limitations': [
            'The tabletop alone does not determine camera translation parallel to the table or world heading.',
            'A fitted plane and nominal mounting offsets are not independent measured world references.',
            'The visible portion of A tape is not the carton grasp center.',
            'No hypothesis is approved for hardware execution or saved to Viam.',
        ],
    }
    for name, yaw in [('configured', -90), ('camera_rotated_180_degrees', 90)]:
        camera_pose = dict(scene.frames['cam']['poseInObserverFrame']['pose'])
        camera_pose['theta'] = yaw
        transform = flange @ pose_matrix(camera_pose)
        normal = transform[:3, :3] @ plane['normal']
        center = transform[:3, :3] @ plane['center_mm'] + transform[:3, 3]*1000
        report['hypotheses'][name] = {
            'camera_theta_degrees': yaw,
            'table_tilt_degrees': float(np.degrees(np.arccos(np.clip(abs(normal[2]), 0, 1)))),
            'table_sample_center_world_mm': center.tolist(),
            'table_height_discrepancy_mm': float(center[2] - report['table_model_top_z_mm']),
        }
    output = ROOT / 'artifacts/diagnosis/restored-view-consistency.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
