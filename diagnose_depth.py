"""Offline depth/scene consistency check. Does not connect to or move the arm."""
import json
from pathlib import Path

import numpy as np

from scene_sweep import Scene, pose_matrix

ROOT = Path(__file__).parent


def fit_plane(points, tolerance_mm=3, seed=43):
    """Robust plane in millimeters; normal points away from camera origin."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 100:
        raise ValueError('Need at least 100 three-dimensional points')
    if not np.isfinite(points).all():
        raise ValueError('Non-finite depth points')
    rng = np.random.default_rng(seed)
    best = np.zeros(len(points), dtype=bool)
    for _ in range(300):
        a, b, c = points[rng.choice(len(points), 3, replace=False)]
        n = np.cross(b - a, c - a)
        length = np.linalg.norm(n)
        if length < 1e-6:
            continue
        n /= length
        inliers = abs((points - a) @ n) < tolerance_mm
        if inliers.sum() > best.sum():
            best = inliers
    if best.sum() < 100:
        raise ValueError('Insufficient planar support')
    center = points[best].mean(axis=0)
    _, singular, axes = np.linalg.svd(points[best] - center, full_matrices=False)
    if singular[1] < 1e-6:
        raise ValueError('Degenerate plane points')
    normal = axes[-1]
    if normal @ center < 0:
        normal = -normal
    return {
        'normal': normal.tolist(), 'center_mm': center.tolist(),
        'distance_from_camera_mm': float(normal @ center),
        'inlier_fraction': float(best.mean()),
        'rms_mm': float(np.sqrt(np.mean(((points[best] - center) @ normal)**2))),
    }


def main():
    observation = json.loads((ROOT / 'artifacts/current-observation.json').read_text())
    depth = np.load(ROOT / 'artifacts/current-depth.npy')
    intr = observation['camera_properties']['intrinsicParameters']
    if depth.shape != (intr['heightPx'], intr['widthPx']):
        raise ValueError('Depth dimensions do not match color intrinsics')
    scene = Scene()
    tf = scene.forward(observation['arm_joints']['values'])['link_eef'] @ pose_matrix(
        scene.frames['cam']['poseInObserverFrame']['pose'])
    report = {
        'captured_at': observation['captured_at'],
        'scope': 'Diagnostic only. Assumes depth aligned to color. Regions manually identified in the saved image. No wall calibration or motion clearance certification.',
        'camera_frame_used': scene.frames['cam'],
        'regions': {},
    }
    for name, bounds in {'table_left': (50, 50, 600, 650), 'panel_right': (800, 50, 1200, 650)}.items():
        x0, y0, x1, y1 = bounds
        v, u = np.mgrid[y0:y1:5, x0:x1:5]
        z = depth[v, u]
        valid = (z > 50) & (z < 2000)
        result = {'bounds_uv': bounds, 'valid_depth_fraction': float(valid.mean())}
        if valid.mean() < 0.6:
            result['result'] = 'Insufficient depth coverage; do not infer wall position.'
        else:
            u, v, z = u[valid], v[valid], z[valid]
            points = np.column_stack(((u-intr['centerXPx'])*z/intr['focalXPx'],
                                      (v-intr['centerYPx'])*z/intr['focalYPx'], z))
            plane = fit_plane(points)
            normal = tf[:3, :3] @ plane['normal']
            center = tf[:3, :3] @ plane['center_mm'] + tf[:3, 3] * 1000
            result.update(plane=plane, configured_world_normal=normal.tolist(),
                          configured_world_center_mm=center.tolist(),
                          tilt_from_horizontal_degrees=float(np.degrees(np.arccos(np.clip(abs(normal[2]), 0, 1)))))
        report['regions'][name] = result
    path = ROOT / 'artifacts/diagnosis/depth-consistency.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
