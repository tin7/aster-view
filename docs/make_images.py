"""Regenerates the gallery images of the README (docs/img/) from the two examples.

    python docs/make_images.py            (from the repository root; about 1 min)

Renders and figures come from the package itself (Scene, make_figure, med_line,
med_history), so they show exactly what a user gets. The screenshots of the
viewer page are taken separately (they need a browser).
"""
import os
import shutil
import tempfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from aster_view import server  # noqa: E402
from aster_view.figure import make_figure  # noqa: E402
from aster_view.medfile import open_med  # noqa: E402
from aster_view.scene import Scene  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "img")
PLATE = os.path.join(ROOT, "examples", "plate_hole", "plate_resu.med")
TUBE = os.path.join(ROOT, "examples", "thick_tube", "tube_resu.med")
TMP = tempfile.mkdtemp()
os.environ["ASTER_VIEW_OUT"] = TMP
SIZE = (1600, 1000)


def scene(path, size=SIZE, **kw):
    sc = Scene(open_med(path), size=size)
    sc.show_text = False
    for k, v in kw.items():
        setattr(sc, k, v)
    sc.update()
    return sc


def camera(sc, view="+z", elevation=0.0, azimuth=0.0, zoom=1.0, focus=None, parallel=False):
    sc.set_view(view)
    cam = sc.ren.GetActiveCamera()
    cam.Elevation(elevation)
    cam.Azimuth(azimuth)
    cam.OrthogonalizeViewUp()
    cam.SetParallelProjection(1 if parallel else 0)
    sc.fit()
    if focus is not None:
        d = np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint())
        cam.SetFocalPoint(*focus)
        cam.SetPosition(*(np.asarray(focus) + d))
    sc.zoom(zoom)


def save(sc, name, size=SIZE, width=1200):
    """Renders at size and saves a copy shrunk to width (lighter, with better antialiasing)."""
    path = os.path.join(OUT, name)
    sc.screenshot(path, size)
    sc.rw.Finalize()
    if width and size[0] > width:
        shrink(path, name, width)
    return path


def shrink(src, name, width):
    """Copy of a 600 dpi PNG at a width that suits a README."""
    im = Image.open(src).convert("RGB")
    h = round(im.height * width / im.width)
    im.resize((width, h), Image.LANCZOS).save(os.path.join(OUT, name), optimize=True)


def results():
    # 1. von Mises (nodal, smooth) on the deformed plate, with the elements
    sc = scene(PLATE, field="SIGM_NOEU", comp="VMIS", representation="surface_edges", warp_scale=30,
               bar_title="von Mises (MPa)")
    camera(sc, elevation=-55, azimuth=20, zoom=1.05)
    save(sc, "gallery_vmis.png")
    # 2. stress bands seen from the top, like contour lines
    sc = scene(PLATE, field="SIGM_NOEU", comp="SIXX", bands=12, cmap="Turbo", bar_title="SIXX (MPa)")
    camera(sc, view="+z", parallel=True, zoom=1.0)
    save(sc, "gallery_bands.png")
    # 3. tube: hoop stress, transverse slice and the rest of the part translucent
    sc = scene(TUBE, field="SIEF_ELGA", comp="SITT", representation="surface_edges", clip_mode="slice",
               clip_origin=np.array([0.0, 0.0, 50.0]), clip_normal=np.array([0.0, 0.0, 1.0]),
               bar_title="SITT (MPa)")
    camera(sc, view="iso", zoom=1.05)
    save(sc, "gallery_slice.png")


def paper():
    figs = os.path.join(TMP, "figs")
    # stress concentration, top view, horizontal bar and a length scale
    sc = scene(PLATE, size=(1400, 1400), field="SIGM_NOEU", comp="SIXX")
    camera(sc, view="+z", parallel=True)
    r = make_figure(sc, figs, "paper_sixx", width_in=3.46, bar="horizontal", label=r"$\sigma_{xx}$ (MPa)",
                    scalebar=True, sb_factor=1.0, sb_unit="mm")
    sc.rw.Finalize()
    shrink(r["png"], "paper_sixx.png", 900)
    # plastic strain near the hole, in %, vertical bar
    sc = scene(PLATE, size=(1400, 1100), field="VARI_NOEU", comp="V1", cmap="Viridis",
               representation="surface_edges", edge_color="#5a5a64")
    sc.range = (0.0, sc.last_info["max"])
    sc.update()
    camera(sc, view="+z", parallel=True, zoom=2.6, focus=(4.0, 12.0, 4.0))
    r = make_figure(sc, figs, "paper_peeq", width_in=3.46, bar="vertical", label=r"$\bar{\varepsilon}^{p}$ (%)",
                    factor=100.0, scalebar=True, sb_factor=1.0, sb_unit="mm")
    sc.rw.Finalize()
    shrink(r["png"], "paper_peeq.png", 900)
    # profile along the ligament and history at the hole, same journal style
    out = server.med_line(PLATE, "SIGM_NOEU", "SIXX", p0=[0, 10, 4], p1=[0, 40, 4], n=120,
                          xlabel="distance from the hole (mm)", ylabel=r"$\sigma_{xx}$ (MPa)")
    shrink(out[0].split("Plot: ")[1].split(" ")[0], "paper_line.png", 900)
    out = server.med_history(PLATE, "VARI_ELGA_NOMME", "EPSPEQ", group="Plate", reduce="max",
                             xlabel="load factor", ylabel=r"max $\bar{\varepsilon}^{p}$")
    shrink(out[0].split("Plot: ")[1].split(" ")[0], "paper_history.png", 900)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    results()
    paper()
    shutil.rmtree(TMP, ignore_errors=True)
    print("images in", OUT)
