"""VTK scene (off-screen): rendering, values per element and saved views."""
import json

import numpy as np
import pytest
from conftest import lame

pytest.importorskip("vtk")
pytestmark = pytest.mark.render

from aster_view.medfile import open_med  # noqa: E402
from aster_view.scene import Scene  # noqa: E402


@pytest.fixture
def scene(example):
    sc = Scene(open_med(example), size=(640, 400))
    yield sc
    sc.rw.Finalize()


def test_render_png(scene, tmp_path):
    scene.field, scene.comp = "SIEF_ELGA", "SITT"
    scene.update()
    out = tmp_path / "a.png"
    scene.screenshot(str(out))
    assert out.stat().st_size > 5000


@pytest.mark.parametrize("mode", ["min", "max"])
def test_cell_reduce_reaches_the_gauss_extremes(scene, mode):
    scene.field, scene.comp, scene.cell_reduce = "SIEF_ELGA", "SIRR", mode
    info = scene.update()
    if mode == "min":
        assert info["min"] == pytest.approx(info["pg_min"])
    else:
        assert info["max"] == pytest.approx(info["pg_max"])
    assert -10.0 < info["pg_min"] < info["pg_max"] < 0.0


def test_probe_is_exact_at_nodes(scene):
    r = scene.res
    scene.field, scene.comp = "DEPL", "DR"
    scene.update()
    x = r.mesh.coords[100]
    v = scene.probe([x])[0]
    assert v == pytest.approx(lame(np.hypot(x[0], x[1]))[2], rel=1e-4)


def test_saved_views_accept_old_spanish_names(scene, tmp_path):
    old = {"field": "SIEF_ELGA", "comp": "SIRR", "representation": "Superficie con aristas",
           "clip_mode": "Sección", "cell_reduce": "máx. |valor|", "background": "Negro", "cmap": "Grises"}
    scene.apply_settings(old)
    s = scene.get_settings()
    assert (s["representation"], s["clip_mode"], s["cell_reduce"], s["background"], s["cmap"]) == \
        ("surface_edges", "slice", "absmax", "black", "Grayscale")
    json.dumps(s)


def test_probe_on_a_symmetry_plane(scene):
    """Points on a boundary face (nodes at x = 3e-15 from cos 90°) are still found."""
    scene.field, scene.comp = "DEPL", "DR"
    scene.update()
    v = scene.probe([[0.0, 55.0, 50.0], [0.0, 70.0, 50.0]])
    assert v[0] == pytest.approx(lame(55.0)[2], rel=1e-3)
    assert np.isnan(v[1])                       # outside the tube


def test_picks_on_the_deformed_shape(example):
    """Points clicked on the deformed surface (×30, curved faces drawn with chords) always get
    a value, also near the hole where the displacement changes fast inside an element."""
    import os
    import vtk
    plate = os.path.join(os.path.dirname(example), "..", "plate_hole", "plate_resu.med")
    sc = Scene(open_med(plate), size=(900, 600))
    sc.field, sc.comp, sc.warp_scale = "SIGM_NOEU", "VMIS", 30.0
    sc.update()
    sc.set_view("+z")
    cam = sc.ren.GetActiveCamera()
    cam.Elevation(-55)
    cam.Azimuth(20)
    sc.fit()
    sc.rw.Render()
    X, U = sc.mesh.coords, sc._U
    rng = np.random.default_rng(1)
    vals = []
    for _ in range(120):
        th, z = rng.uniform(0, np.pi / 2), rng.uniform(0.2, 3.8)
        target = np.array([10 * np.cos(th), 10 * np.sin(th), z])       # on the hole
        k = np.argmin(np.linalg.norm(X - target, axis=1))
        c = vtk.vtkCoordinate()
        c.SetCoordinateSystemToWorld()
        c.SetValue(*(target + 30 * U[k]))
        hit = sc.pick_at(*c.GetComputedDoubleDisplayValue(sc.ren))
        if hit is not None:
            vals.append(sc.probe([hit["x0"]])[0])
    sc.rw.Finalize()
    assert len(vals) > 100 and not np.isnan(vals).any()


def _drag(sc, x0, y0, x1, y1):
    def ev(name, x, y):
        sc.iren.SetEventInformation(int(x), int(y), 0, 0, chr(0), 0, None)
        sc.iren.InvokeEvent(name)
    ev("MouseMoveEvent", x0, y0)
    ev("LeftButtonPressEvent", x0, y0)
    for k in range(1, 21):
        ev("MouseMoveEvent", x0 + (x1 - x0) * k / 20, y0 + (y1 - y0) * k / 20)
    ev("LeftButtonReleaseEvent", x1, y1)


def test_color_bar_placement(scene):
    scene.field, scene.comp = "SIEF_ELGA", "SITT"
    scene.update()
    scene.rw.Render()
    for pos, horizontal in (("right", False), ("left", False), ("top", True), ("bottom", True)):
        scene.bar_pos = pos
        scene.rw.Render()
        (x, y), (w, h) = scene.bar_rep.GetPosition(), scene.bar_rep.GetPosition2()
        assert 0 <= x and x + w <= 1 and 0 <= y and y + h <= 1, pos
        assert bool(scene.bar.GetOrientation() == 0) == horizontal, pos
    # arrastrada con el mouse más allá del borde de arriba: queda dentro de la vista y se recuerda
    scene.bar_pos = "right"
    scene.rw.Render()
    W, H = scene.rw.GetSize()
    (x, y), (w, h) = scene.bar_rep.GetPosition(), scene.bar_rep.GetPosition2()
    moved = []
    scene.on_bar = lambda: moved.append(True)
    _drag(scene, (x + w / 2) * W, (y + h / 2) * H, 0.5 * W, 1.6 * H)
    (x, y), (w, h) = scene.bar_rep.GetPosition(), scene.bar_rep.GetPosition2()
    assert moved and scene.bar_pos == "custom" and y + h <= 1 + 1e-9 and x >= 0
    s = scene.get_settings()
    assert s["bar_pos"] == "custom" and len(s["bar_custom"]) == 5
