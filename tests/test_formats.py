"""ELNO fields, 2D models and files with several meshes (tests/data, made with code_aster 17.4)."""
import os

import numpy as np
import pytest

from aster_view.derived import evaluate, flatten, label
from aster_view.medfile import MedError, open_med

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
AXIS = os.path.join(DATA, "axis_resu.med")
TRI = os.path.join(DATA, "dplan_t6_resu.med")
MULTI = os.path.join(DATA, "multi_resu.med")


def test_elno_values_sit_on_the_element_nodes():
    """Averaging SIGM_ELNO over the elements around each node gives code_aster's SIGM_NOEU."""
    r = open_med(AXIS)
    fe, fn = r.read("SIGM_ELNO"), r.read("SIGM_NOEU")
    assert fe.info.support == "ELNO"
    m = r.mesh
    acc, cnt = np.zeros((m.n_nodes, 4)), np.zeros(m.n_nodes)
    for t, v in fe.cells.items():
        conn = m.blocks[t].conn[:, :v.shape[1]]
        np.add.at(acc, conn.ravel(), v.reshape(-1, 4))
        np.add.at(cnt, conn.ravel(), 1)
    used = cnt > 0
    assert np.allclose(acc[used] / cnt[used, None], fn.node[used], rtol=1e-12, atol=1e-12)
    v, X, labels = flatten(r, fe, evaluate(r, fe, "SIXX"))
    i = int(np.argmin(v))
    assert labels[0] == "elno" and "of cell" in label(labels, i)
    assert np.allclose(X[i], m.coords[labels[2][i] - 1])     # the value is placed on its node


@pytest.mark.parametrize("path", [AXIS, TRI])
def test_2d_von_mises_matches_code_aster(path):
    r = open_med(path)
    assert r.mesh.space_dim == 2
    s, q = r.read("SIEF_ELGA"), r.read("SIEQ_ELGA")
    assert s.info.components == ["SIXX", "SIYY", "SIZZ", "SIXY"]
    mine, _, _ = flatten(r, s, evaluate(r, s, "VMIS"))
    ref, _, _ = flatten(r, q, evaluate(r, q, "VMIS"))
    assert np.allclose(mine, ref, rtol=1e-10, atol=1e-9)


def test_2d_offers_no_cylindrical_components():
    from aster_view.derived import derived_names
    r = open_med(AXIS)
    comps = r.field("SIEF_ELGA").components
    assert derived_names(comps, r.mesh.space_dim) == ["VMIS", "TRACE"]
    assert derived_names(r.field("DEPL").components, 2) == ["NORM"]


def test_axisymmetric_tube_against_lame():
    """AXIS: SIXX = σr, SIZZ = σθ, SIYY = σz (free end: 0)."""
    p, a, b = 10.0, 50.0, 60.0
    A = p * a ** 2 / (b ** 2 - a ** 2)
    B = A * b ** 2
    r = open_med(AXIS)
    fs = r.read("SIEF_ELGA", step=-1)
    sr, X, _ = flatten(r, fs, evaluate(r, fs, "SIXX"))
    st, _, _ = flatten(r, fs, evaluate(r, fs, "SIZZ"))
    sz, _, _ = flatten(r, fs, evaluate(r, fs, "SIYY"))
    rr = X[:, 0]
    assert np.abs(sr - (A - B / rr ** 2)).max() < 0.005 * p
    assert np.abs(st - (A + B / rr ** 2)).max() < 0.005 * p
    assert np.abs(sz).max() < 0.005 * p


def test_several_meshes():
    base = open_med(MULTI)
    assert base.mesh_names == ["00000001", "00000002"] and base.mesh_name == "00000001"
    with pytest.raises(MedError, match="ambiguous"):
        base.field("DEPL")
    v3, v2 = base.view("00000001"), base.view("00000002")
    assert (v3.mesh.space_dim, v2.mesh.space_dim) == (3, 2)
    assert [f.short for f in v3.fields.values()] == ["DEPL", "SIEF_ELGA"]
    assert [f.short for f in v2.fields.values()] == ["DEPL", "SIEF_ELGA"]
    d3, d2 = v3.read("DEPL"), v2.read("DEPL")
    assert d3.node.shape == (v3.mesh.n_nodes, 3) and d2.node.shape == (v2.mesh.n_nodes, 2)
    # same tube, twice the pressure in the 2D model: twice the radial displacement of the bore
    assert np.nanmax(d2.node[:, 0]) == pytest.approx(2 * np.nanmax(np.hypot(d3.node[:, 0], d3.node[:, 1])), rel=1e-3)
    # every field is read on its own mesh, also from the whole file
    assert base.read("r2d_____SIEF_ELGA").cells["QU8"].shape[0] == v2.mesh.blocks["QU8"].ne
    with pytest.raises(MedError, match="No mesh"):
        base.view("nope")


@pytest.mark.render
def test_scene_on_2d_and_mesh_switch(tmp_path):
    pytest.importorskip("vtk")
    from aster_view.scene import Scene
    sc = Scene(open_med(TRI), size=(400, 300))
    sc.field, sc.comp = "SIEF_ELGA", "VMIS"
    sc.update()
    sc.set_view("iso")                       # 2D: seen from the front, y up
    cam = sc.ren.GetActiveCamera()
    assert np.allclose(cam.GetViewUp(), (0, 1, 0)) and abs(cam.GetDirectionOfProjection()[2]) == pytest.approx(1)
    sc.screenshot(str(tmp_path / "t6.png"))
    sc.rw.Finalize()
    base = open_med(MULTI)
    sc = Scene(base, size=(400, 300))
    assert sc.mesh.space_dim == 3 and sc.field_choices() == ["DEPL", "SIEF_ELGA"]
    sc.set_result(base.view("00000002"))
    sc.field, sc.comp = "SIEF_ELGA", "VMIS"
    info = sc.update()
    assert sc.mesh.space_dim == 2 and info["n"] == sc.mesh.blocks["QU8"].ne
    assert sc.get_settings()["mesh"] == "00000002"
    sc.rw.Finalize()


@pytest.mark.render
def test_mcp_tools_choose_the_mesh(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from aster_view import server
    with pytest.raises(Exception, match="ambiguous"):
        server.med_stats(MULTI, "SIEF_ELGA", "VMIS")
    out = server.med_stats(MULTI, "SIEF_ELGA", "VMIS", mesh="00000002")
    assert "360 of 360" in out
    out = server.med_stats(AXIS, "SIGM_ELNO", "SIXX")
    assert "support ELNO" in out and "of cell" in out
    txt = server.med_render(MULTI, field="r2d_____SIEF_ELGA", component="SIXX", width=400, height=300)[0]
    assert "At the Gauss points" in txt
    info = server.med_info(MULTI)
    assert "## Mesh '00000002' (2D)" in info and "r2d_____DEPL" in info
