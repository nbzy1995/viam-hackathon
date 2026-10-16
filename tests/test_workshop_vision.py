"""Search acceptance must not weaken placement verification."""
from types import SimpleNamespace
import numpy as np
import pytest
import workshop_vision as script


def test_twenty_cm_pickup_boundary_and_overlapping_station_regions(monkeypatch):
    monkeypatch.setattr(script, 'cap_center', lambda pcd, _: np.array(pcd))
    a = script.STATIONS['A']
    item = SimpleNamespace(point_cloud=[a[0]+200, a[1], 146])
    cap, _ = script.locate_carton([item], None)
    assert cap[0] == a[0]+200
    item.point_cloud[0] += 1
    with pytest.raises(RuntimeError, match='20 cm'):
        script.locate_carton([item], None)
    # B is within A's expanded search circle, but is not a successful placement at A.
    with pytest.raises(RuntimeError, match='placement at A'):
        script.verify_placement(np.array([*script.STATIONS['B'],146]), 'A')


def test_blue_marker_does_not_prevent_search_for_smaller_carton(monkeypatch):
    def cap(pcd, _):
        if pcd == b'marker-large': raise RuntimeError('No upright carton')
        return np.array([*script.STATIONS['A'],146.])
    monkeypatch.setattr(script, 'cap_center', cap)
    carton, station = script.locate_carton([
        SimpleNamespace(point_cloud=b'marker-large'),
        SimpleNamespace(point_cloud=b'carton')], None)
    assert station == 'A'
    np.testing.assert_allclose(carton[:2], script.STATIONS['A'])
    with pytest.raises(script.CartonNotVisible):
        script.locate_carton([SimpleNamespace(point_cloud=b'marker-large')], None)
