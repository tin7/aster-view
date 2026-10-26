"""Reader and cylindrical components against the exact Lamé solution (no VTK needed)."""
import numpy as np
import pytest
from conftest import P, lame

from aster_view.derived import Axis, evaluate, flatten, stats
from aster_view.medfile import MedError, open_med


def test_contents(example):
    r = open_med(example)
    assert {f.short for f in r.fields.values()} == {"DEPL", "SIEF_ELGA", "SIGM_NOEU"}
    f = r.field("SIEF_ELGA")
    assert f.support == "ELGA" and [s.time for s in f.steps] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert r.mesh.n_nodes == 1667 and r.mesh.blocks["H20"].ne == 288
    assert {"Tube", "Inner", "Outer", "SymX", "SymY", "Bottom", "Top"} <= set(r.mesh.cell_groups)


def test_auto_axis_is_the_tube_axis(example):
    a = Axis.auto(open_med(example).mesh)
    assert np.allclose(a.point[:2], 0, atol=1e-9) and np.allclose(a.direction, [0, 0, 1])


@pytest.mark.parametrize("comp, k, tol", [("SIRR", 0, 0.01 * P), ("SITT", 1, 0.005 * P)])
def test_stresses_at_gauss_points(example, comp, k, tol):
    r = open_med(example)
    fs = r.read("SIEF_ELGA", step=-1)
    v, X, labels = flatten(r, fs, evaluate(r, fs, comp, Axis.auto(r.mesh)))
    assert labels[0] == "celda" and len(v) == 288 * 27
    exact = lame(np.hypot(X[:, 0], X[:, 1]))[k]
    assert np.abs(v - exact).max() < tol


def test_axial_stress_is_zero(example):
    r = open_med(example)
    fs = r.read("SIEF_ELGA", step=-1)
    v, _, _ = flatten(r, fs, evaluate(r, fs, "SIAA", Axis.auto(r.mesh)))
    assert np.abs(v).max() < 0.005 * P


def test_radial_displacement(example):
    r = open_med(example)
    fs = r.read("DEPL", step=-1)
    v, X, _ = flatten(r, fs, evaluate(r, fs, "DR", Axis.auto(r.mesh)))
    exact = lame(np.hypot(X[:, 0], X[:, 1]))[2]
    assert np.abs(v / exact - 1).max() < 1e-4


def test_time_scaling(example):
    """The load is a ramp: every field at t = 0.5 is half of the one at t = 1."""
    r = open_med(example)
    half, full = r.read("SIEF_ELGA", time=0.5), r.read("SIEF_ELGA", time=1.0)
    for t in full.cells:
        assert np.allclose(half.cells[t], 0.5 * full.cells[t], rtol=1e-9, atol=1e-9)


def test_stats_and_groups(example):
    r = open_med(example)
    fs = r.read("DEPL", step=-1)
    v, _, labels = flatten(r, fs, evaluate(r, fs, "DR", Axis.auto(r.mesh)), "Inner")
    s = stats(v)
    assert labels[0] == "nodo" and s["definidos"] == len(v) > 0
    assert np.isclose(s["media"], lame(50.0)[2], rtol=1e-4)


def test_errors(example, tmp_path):
    r = open_med(example)
    with pytest.raises(MedError, match="No field"):
        r.field("TEMP")
    with pytest.raises(MedError, match="No group"):
        r.mesh.group_cells("Nope")
    with pytest.raises(MedError, match="not found"):
        open_med(tmp_path / "missing.med")
    bad = tmp_path / "truncated.med"
    bad.write_bytes(open(example, "rb").read()[:200000])
    with pytest.raises(MedError, match="TRUNCATED"):
        open_med(bad)
