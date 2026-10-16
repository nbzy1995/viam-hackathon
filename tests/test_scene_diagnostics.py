"""Three regressions supporting the retained geometry diagnostics."""
import json
import copy
import pytest
import numpy as np
from scene_sweep import DATA, Scene, pose_matrix


def captured_scene(**kwargs):
    # Keep incident regressions independent of later live scene corrections.
    state = json.loads((DATA / 'pre-wall-correction-state.json').read_text())
    return Scene(state=state, **kwargs)


def test_model_matches_saved_viam_flange_telemetry():
    scene = captured_scene()
    xyz = scene.forward(scene.state['joints']['values'])['link_eef'][:3, 3] * 1000
    np.testing.assert_allclose(xyz, [scene.state['pose'][k] for k in ('x', 'y', 'z')], atol=0.001)


def test_camera_orientation_matches_live_viam_basis_transform():
    state = json.loads((DATA / 'tutorial-live-readback.json').read_text())
    camera = next(f for f in state['frames'] if f['referenceFrame'] == 'cam')
    actual = pose_matrix(camera['poseInObserverFrame']['pose'])
    expected = json.loads((DATA / 'camera-frame-basis-readback.json').read_text())
    np.testing.assert_allclose(actual[:3, :3], expected['rotation_matrix'], atol=1e-12)
    np.testing.assert_allclose(actual[:3, 3] * 1000, expected['translation_mm'], atol=1e-10)


def test_front_wall_on_negative_x_uses_inside_face_toward_base():
    state = copy.deepcopy(captured_scene().state)
    front = next(f for f in state['frames'] if f['referenceFrame'] == 'wall-front')
    front['poseInObserverFrame']['pose']['x'] = -450
    scene = Scene(state=state)
    assert scene.boundaries['wall-front'] == pytest.approx((0, 1, -0.400))
    assert scene.clearances(state['joints']['values'])['wall-front']['clearance_mm'] > 0
    buffered = Scene(state=state, wall_buffer_mm=50)
    assert buffered.boundaries['wall-front'] == pytest.approx((0, 1, -0.350))
