"""Journal-style figure for a paper.

VTK draws ONLY the geometry (white background, no shading: the colors are those of the
bar) and matplotlib adds the bar and the text with journal rcParams (DejaVu Sans
9/10 pt, 600 dpi). The PDF has a tight bbox; to keep the font the same size as in the
other one-column figures, include it with
width = pdf_width / 243 pt \\linewidth (one column of the Elsevier two-column class cas-dc;
reported when the figure is made).
Next to each figure, a .json recipe keeps the whole state (file, field, time step,
camera, colors...) to regenerate it exactly (MCP tool med_figure).
"""
from __future__ import annotations

import base64
import json
import os
import re

import numpy as np

from .i18n import canonical

PAPER_RC = {
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
    "font.size": 9, "axes.labelsize": 10,
    "xtick.labelsize": 8.5, "ytick.labelsize": 8.5, "legend.fontsize": 8,
    "axes.linewidth": 0.8, "lines.linewidth": 1.4,
    "savefig.dpi": 600, "savefig.bbox": "tight", "pdf.fonttype": 42,
    "legend.frameon": False,
}
LINEWIDTH_PT = 243.0   # \linewidth of one column in the Elsevier two-column class (cas-dc)
WIDTHS = {"1col": 3.46, "1.5col": 5.2, "2col": 7.1}     # labels in i18n.py
BARS = ("horizontal", "vertical", "none")


def width_inches(w):
    """Width in inches: key ('1col'), its label in any language, or a number."""
    k = canonical("fig_width", w)
    if k in WIDTHS:
        return WIDTHS[k]
    return float(str(w).replace(",", "."))

# default labels (no units: the file does not store them; complete them by hand)
LABELS = {"SIRR": r"$\sigma_r$", "SITT": r"$\sigma_\theta$", "SIAA": r"$\sigma_z$", "SIRT": r"$\sigma_{r\theta}$",
          "VMIS": "von Mises stress", "DR": r"$u_r$", "DT": r"$u_\theta$", "DA": r"$u_z$",
          "DX": r"$u_x$", "DY": r"$u_y$", "DZ": r"$u_z$", "NORM": r"$|u|$"}


def default_label(comp):
    return LABELS.get(comp, comp or "")


def _trim(img, pad=6):
    mask = np.any(img < 250, axis=2)
    rows, cols = np.where(mask.any(1))[0], np.where(mask.any(0))[0]
    if not len(rows):
        return img
    r0, r1 = max(rows[0] - pad, 0), min(rows[-1] + pad + 1, img.shape[0])
    c0, c1 = max(cols[0] - pad, 0), min(cols[-1] + pad + 1, img.shape[1])
    return img[r0:r1, c0:c1]


def _nice(x):
    if x <= 0:
        return 1.0
    e = 10 ** np.floor(np.log10(x))
    for m in (1, 2, 5, 10):
        if m * e >= x * 0.999:
            return m * e
    return 10 * e


def _pdf_width_pt(path):
    with open(path, "rb") as f:
        m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", f.read())
    return float(m.group(3)) - float(m.group(1)) if m else None


def make_figure(scene, out_dir, name, width_in=3.46, bar="horizontal", label=None, factor=1.0,
                nticks=5, shading=False, scalebar=False, sb_factor=1000.0, sb_unit="mm",
                dpi=600, preview_dpi=110):
    """Writes <name>.pdf, <name>.png (600 dpi) and <name>.json (recipe). Returns the paths,
    the PDF width and the suggested \\includegraphics line."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm, Normalize
    from matplotlib.font_manager import FontProperties
    from matplotlib.ticker import MaxNLocator
    from mpl_toolkits.axes_grid1.anchored_artists import AnchoredSizeBar

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, name)
    factor = float(factor or 1.0)
    bar = canonical("fig_bar", bar or "horizontal")
    has_bar = bool(scene.field) and bar != "none"
    with mpl.rc_context(PAPER_RC):
        vw, vh = scene.rw.GetSize()
        img_w_in = width_in * (0.80 if (has_bar and bar == "vertical") else 1.0)
        w_px = int(round(img_w_in * dpi))
        h_px = int(round(w_px * vh / max(vw, 1)))
        img, upp = scene.render_paper(w_px, h_px, shading=shading)
        img = _trim(img)
        ih, iw = img.shape[:2]
        # explicit layout in inches (with colorbar(ax=...) the bar comes out tiny
        # when the image is flat, e.g. a whole long tube): bar 0.12 in thick,
        # 70 % of the width if horizontal; length scale outside, top right
        W, tb, gap = width_in, 0.12, 0.08
        top = 0.28 if scalebar and upp else 0.02
        if has_bar and bar == "vertical":
            wi = W - 0.95
            hi_ = wi * ih / iw
            Lb = max(0.85 * hi_, 1.2)
            H = max(hi_, Lb) + top + 0.05
            y_img = (H - top - hi_) / 2 if Lb > hi_ else 0.05
            ax_rect = [0, y_img / H, wi / W, hi_ / H]
            cb_rect = [(wi + gap) / W, (y_img + hi_ / 2 - Lb / 2) / H, tb / W, Lb / H]
        else:
            wi, hi_ = W, W * ih / iw
            below = (gap + tb + 0.55) if has_bar else 0.05
            H = hi_ + below + top
            ax_rect = [0, below / H, 1, hi_ / H]
            cb_rect = [0.15, (below - gap - tb) / H, 0.70, tb / H]
        fig = plt.figure(figsize=(W, H))
        ax = fig.add_axes(ax_rect)
        ax.imshow(img, interpolation="lanczos", aspect="auto")
        ax.set_axis_off()
        if has_bar:
            lo, hi = scene.last_range
            rgb = scene.last_rgb
            cmap = ListedColormap(rgb)
            if scene.log:
                norm = LogNorm(lo * factor, hi * factor)
            elif scene.bands and int(scene.bands) > 1:
                norm = BoundaryNorm(np.linspace(lo * factor, hi * factor, len(rgb) + 1), len(rgb))
            else:
                norm = Normalize(lo * factor, hi * factor)
            sm = mpl.cm.ScalarMappable(norm=norm, cmap=cmap)
            cax = fig.add_axes(cb_rect)
            cb = fig.colorbar(sm, cax=cax, orientation="horizontal" if bar == "horizontal" else "vertical")
            if not scene.log and not (scene.bands and int(scene.bands) > 1):
                cb.locator = MaxNLocator(int(nticks))
                cb.update_ticks()
            cb.set_label(label if label is not None else default_label(scene.comp))
            cb.outline.set_linewidth(0.8)
        sb_txt = None
        if scalebar and upp:
            L = _nice(0.2 * iw * upp * sb_factor)
            sb_txt = f"{L:g} {sb_unit}"
            asb = AnchoredSizeBar(ax.transData, L / sb_factor / upp, sb_txt, "lower right", pad=0.1,
                                  borderpad=0.1, frameon=False, size_vertical=max(ih * 0.006, 2), color="k",
                                  fontproperties=FontProperties(size=8.5), label_top=True,
                                  bbox_to_anchor=(1.0, 1.0), bbox_transform=ax.transAxes)
            ax.add_artist(asb)
        fig.savefig(base + ".pdf")
        fig.savefig(base + ".png", dpi=dpi)
        fig.savefig(base + "_preview.png", dpi=preview_dpi)
        plt.close(fig)
    w_pt = _pdf_width_pt(base + ".pdf")
    receta = scene.get_settings()
    receta["figura"] = {"name": name, "width_in": width_in, "bar": bar, "label": label, "factor": factor,
                        "nticks": nticks, "shading": shading, "scalebar": scalebar, "sb_factor": sb_factor,
                        "sb_unit": sb_unit, "dpi": dpi}
    with open(base + ".json", "w") as f:
        json.dump(receta, f, indent=1, ensure_ascii=False)
    latex = (f"\\includegraphics[width={w_pt / LINEWIDTH_PT:.2f}\\linewidth]{{{name}.pdf}}" if w_pt else "")
    return {"pdf": base + ".pdf", "png": base + ".png", "preview": base + "_preview.png", "receta": base + ".json",
            "ancho_pt": w_pt, "latex": latex, "escala": sb_txt, "sin_proyeccion_paralela": bool(scalebar and not upp)}


def preview_data_url(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()
