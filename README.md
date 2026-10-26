# Aster View

[![tests](https://github.com/tin7/aster-view/actions/workflows/tests.yml/badge.svg)](https://github.com/tin7/aster-view/actions/workflows/tests.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**English** · [Español](README.es.md) · [Français](README.fr.md)

Interactive viewer and read-only [MCP](https://modelcontextprotocol.io) server for **code_aster MED results** (`.med`, `.rmed`).

- **Viewer**: ParaView-like viewer that runs in the browser or in a VS Code tab. You can browse fields and time steps, show the deformed shape, cut with any plane, read values with a click, inspect Gauss points and export journal figures.
- **VS Code extension**: right-click a `.med` file → *Open in Aster View*.
- **MCP server** (`aster-med`): lets an AI assistant (Claude Code, Claude Desktop or any MCP client) read numbers, render images, make figures and open the viewer for you. It never runs simulations and never modifies your files.
- **Three languages**: English, Español, Français. You pick the language in the viewer and it is remembered.

![Aster View: von Mises stress on the deformed plate with a hole, with the elements and two values read with the eyedropper](docs/img/viewer.png)

The viewer, the images and the MCP server share one reader and one VTK scene, so what the assistant reports is what you see.

## Gallery

| | |
|:---:|:---:|
| ![von Mises stress on the deformed plate](docs/img/gallery_vmis.png) | ![σxx in 12 color bands](docs/img/gallery_bands.png) |
| von Mises stress on the deformed shape (×30), with the elements | σxx in 12 color bands, seen from the top |
| ![Hoop stress on a transverse slice of the tube](docs/img/gallery_slice.png) | ![Plastic zone growing from the hole](docs/img/gallery_plastic.png) |
| hoop stress σθ (cylindrical component) on a transverse slice, the rest translucent | equivalent plastic strain at three time steps |

The journal figures are in [their own section](#journal-figures). All the pictures come from the two examples in [`examples/`](examples) and are regenerated with `python docs/make_images.py`.

## Contents

- [Gallery](#gallery)
- [Installation](#installation)
- [Quick start](#quick-start)
- [The viewer](#the-viewer)
- [Journal figures](#journal-figures)
- [Derived components](#derived-components)
- [MCP server](#mcp-server)
- [Outputs and settings](#outputs-and-settings)
- [How it is verified](#how-it-is-verified)
- [Limitations](#limitations)
- [Development](#development)
- [License and acknowledgements](#license-and-acknowledgements)

## Installation

You need **Python 3.10 or newer**. It has been tested on Linux (Ubuntu, Python 3.11 and 3.12, VTK 9.7, trame 4).
code_aster itself is **not** needed: the MED files are read directly with `h5py`.

### 1. The Python package

In a virtual environment (recommended):

```bash
python3 -m venv ~/venvs/aster-view
source ~/venvs/aster-view/bin/activate
pip install git+https://github.com/tin7/aster-view
```

With conda: `conda create -n aster-view python=3.11 -y && conda activate aster-view`, then the same `pip install` line.

This installs two commands:

| command | what it does |
|---|---|
| `aster-view file.med` | opens the viewer in your browser |
| `aster-mcp` | the MCP server (started by your MCP client, not by you) |

Dependencies, installed automatically: `vtk`, `trame` (+ `trame-vtk`, `trame-vuetify`), `h5py`, `numpy`, `matplotlib` and `mcp`.
Rendering happens off-screen on your machine, and the browser only receives images. No GPU or WebGL is needed.

### 2. The VS Code extension (optional)

1. Download `aster-view-<version>.vsix` from the [latest release](https://github.com/tin7/aster-view/releases).
2. In VS Code: Command Palette (`Ctrl+Shift+P`) → **Extensions: Install from VSIX…** → pick the file.
3. Reload the window.

The extension looks for the `aster-view` command in your `PATH`, in `~/.local/bin` and in your conda environments (`anaconda3`, `miniconda3`, `miniforge3`…). If it lives elsewhere, for example in a venv, set its full path in the setting **Aster View: Executable** (e.g. `/home/me/venvs/aster-view/bin/aster-view`).

### 3. The MCP server (optional)

The MCP client starts the server itself; you only register the command. Use the full path of `aster-mcp`, which you can get with `which aster-mcp` inside the environment.

**Claude Code:**

```bash
claude mcp add --scope user aster-med -- /home/me/venvs/aster-view/bin/aster-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aster-med": { "command": "/home/me/venvs/aster-view/bin/aster-mcp" }
  }
}
```

Other MCP clients: run `aster-mcp` over stdio.

## Quick start

The repository includes two small examples, both computed with code_aster 17.4:

| example | what it shows |
|---|---|
| [`examples/thick_tube`](examples/thick_tube) | quarter of a thick-walled tube under internal pressure (HEXA20, 2.6 MB). Its exact solution is known (Lamé), so it doubles as a test. |
| [`examples/plate_hole`](examples/plate_hole) | quarter of a plate with a hole pulled until it yields (HEXA20, elastic-plastic, 3.3 MB): stress concentration, a plastic zone that grows over time, internal variables at the Gauss points. |

```bash
git clone https://github.com/tin7/aster-view && cd aster-view
aster-view examples/plate_hole/plate_resu.med --field SIGM_NOEU --comp VMIS
```

The browser opens with the von Mises stress. Things to try:

- the **⊞** button in the toolbar shows the elements;
- in the *Pipeline*, the eye of *Deformed shape* turns it on; click its name to change the scale;
- the eye of *Cut* turns on a cut; click *Cut* to pick a preset (X, Y, Z, transverse…);
- the eyedropper reads values with a click; they are listed in the *Values* tab;
- the language and the dark theme are at the top right.

From VS Code: right-click `plate_resu.med` in the explorer → **Open in Aster View (results)**.

With an MCP client, ask something like *"open examples/plate_hole/plate_resu.med in the viewer"* or *"max hoop stress at the Gauss points in examples/thick_tube/tube_resu.med"*.

`aster-view --help` lists the options: `--field`, `--comp`, `--mesh`, `--port`, `--no-browser`, `--lang es|en|fr`, `--timeout`.

## The viewer

![Dark theme: transverse slice of the tube, with the Cut filter selected in the pipeline](docs/img/viewer_cut.png)

The layout follows ParaView:

- **Toolbar** (top):
  - color by field and component and, for Gauss-point fields, the value per element (mean, min, max or max |value| of its Gauss points);
  - representation, element edges and nodes;
  - colormap, invert, rescale to the visible data or over all time steps, color bar;
  - click mode, camera and time controls.
- **Pipeline** (left): the file and four filters, each with an eye to turn it on or off:
  - *deformed shape* (DEPL × scale);
  - *threshold* by value;
  - *cut* (clip, slice or whole cells);
  - *axial window*.

  Clicking an item shows its properties.
- **Tabs** below the pipeline:
  - *Properties* of the selected item. For the file: coloring (colormap, bands, range, log scale, symmetric range, color bar), styling (representation, opacity, shading, color and size of edges and nodes), visible groups, view (background, text, axes), saved views and the cylindrical axis.
  - *Information*: the mesh (nodes, cells by type, bounds) and the fields (support, components, time steps).
  - *Values*: the points read with the eyedropper (value, nearest node, coordinates). They follow changes of time step or component.
  - *Figure*: journal figures, see [below](#journal-figures).
- **Status bar** (bottom): field, component and time, the min/max of what is shown and, for Gauss-point fields, the min/max at the Gauss points. Both are shown because the mean per element hides peaks.
- **Top right**: language and light/dark theme. Both are remembered.

**Mouse.**
- Drag to rotate.
- The wheel zooms **towards the cursor**.
- Shift + drag pans.
- Ctrl + drag rotates in the screen plane.
- Drag the **color bar** to move it, or pull one of its edges to resize it; near the top or bottom it turns horizontal. Quick placements (right, left, top, bottom) are in *Properties → Coloring*, and the placement is saved with views and figure recipes.

**Click modes** (toolbar):
- rotate;
- **hand**: pan without rotating;
- read a value;
- center the view on a point;
- **magnifier**: drag a box to zoom into it, like ParaView's *Zoom to Box* (a single click zooms ×2);
- place the cutting plane.

**Cut:**
- clip, slice or whole cells;
- presets X, Y, Z, transverse, longitudinal (at angle θ) and facing the camera;
- position along the normal, or origin and normal by hand;
- a draggable plane in 3D;
- the rest of the part translucent.

The viewer listens on `localhost` only. It exits by itself 10 minutes after its last browser tab is closed.

**In VS Code**, the viewer opens in a tab. You can open it in several ways:
- right-click the file in the explorer or its tab → *Open in Aster View (results)*;
- **Open With… → Aster View (results)**; from there you can make it the default editor for `*.med`;
- the **Aster View** button in the status bar while a `.med` file is open;
- the chart button in the title bar of the mesh viewer of [VS Code Aster](https://github.com/simvia-tech/vs-code-aster).

Extension settings:
- `asterView.executable`;
- `asterView.openIn`: `vscode` tab or system `browser`;
- `asterView.language`: `auto` = the language last chosen in the viewer; the first time, the VS Code language.

**Relation to VS Code Aster.** The [VS Code Aster](https://github.com/simvia-tech/vs-code-aster) extension by Simvia edits `.comm`/`.export` files, runs studies and shows **meshes and groups**. Aster View complements it with the **results**: fields, time steps, deformed shape, cuts, Gauss points and figures. Both can be installed together.

## Journal figures

The *Paper figure* panel (or the `med_figure` MCP tool) writes a figure in journal style:

- VTK draws only the geometry: white background and, by default, no shading, so the colors match the color bar exactly;
- matplotlib draws the color bar and labels (DejaVu Sans 9/10 pt, 600 dpi);
- the figure is framed like the current view.

| | |
|:---:|:---:|
| ![σxx with a horizontal color bar and a length scale](docs/img/paper_sixx.png) | ![Plastic strain near the hole, vertical color bar](docs/img/paper_peeq.png) |
| ![Profile of σxx along the ligament](docs/img/paper_line.png) | ![History of the maximum plastic strain](docs/img/paper_history.png) |

The top two are made in the *Figure* tab (or with `med_figure`). The bottom two are the plots of `med_line` and `med_history`, which use the same style and are also saved as PDF.

Options:
- width of 1, 1.5 or 2 columns;
- horizontal, vertical or no color bar;
- label with mathtext (`$\sigma_\theta$ (MPa)`) and a factor for the values (e.g. 1000 to go from m to mm);
- length scale bar (with parallel projection).

Output in `<output>/<med name>/figuras/`:
- PDF and 600 dpi PNG;
- a **`.json` recipe** with the full state and camera, so that `med_figure(recipe=...)` regenerates the same figure later;
- the `\includegraphics[width=X\linewidth]` line. Its width keeps the font size equal to other one-column figures of an Elsevier two-column article (column = 243 pt).

## Derived components

Besides the components stored in the file, the following are computed:

- `NORM`;
- `DR` / `DT` / `DA`: cylindrical displacement;
- `SIRR` / `SITT` / `SIAA` / `SIRT` / `SIRA` / `SITA`: stress in cylindrical coordinates, and the same for any other symmetric tensor stored as `<P>XX…<P>YZ`;
- `VMIS` and `TRACE`.

The cylindrical axis runs along the longest side of the bounding box. It goes through the common center of the nodes when they form rings (full, half or quarter tubes), otherwise through the center of the box. You can change it in the *Cylindrical axis* panel or with `axis_point` / `axis_dir`. The radial direction is taken from the **undeformed** geometry.

### 2D models, ELNO fields and several meshes

- **2D models** (`D_PLAN`, `C_PLAN`, `AXIS`): the mesh is drawn in the xy plane, seen from the front and with parallel projection. Stress tensors have 4 components (SIXX, SIYY, SIZZ, SIXY); `VMIS` and `TRACE` are computed from them. Cylindrical components are not offered, because in an axisymmetric model the components already are cylindrical: SIXX = σr, SIYY = σz, SIZZ = σθ.
- **ELNO fields** (`SIGM_ELNO`, `VARI_ELNO`…): one value per node of each element. They are painted like Gauss-point fields (one value per element: mean, min, max or max |value| of its nodes), and statistics and extractions give each value with its element and node.
- **Several meshes in one file** (e.g. two `IMPR_RESU` of results on different meshes): each field is read on its own mesh. The viewer shows a *Mesh* selector in the file properties (and accepts `--mesh`). The MCP tools take the full field name, e.g. `r2d_____DEPL`, or `mesh=` when the same short name exists on more than one mesh; `med_info` lists the meshes and their fields.

## MCP server

| tool | what it does |
|---|---|
| `med_info` | mesh, groups and fields (support, components, time steps, profile); detects truncated files |
| `med_steps` | time steps of a field |
| `med_stats` | min/max with their location, mean and percentiles, over a group or the whole model |
| `med_history` | time history over a group, at a node, or at the point nearest to (x, y, z) (table + journal-style plot, PNG and PDF) |
| `med_line` | profile along a segment, also on a boundary face such as a symmetry plane (CSV + journal-style plot, PNG and PDF) |
| `med_extract` | raw values with coordinates over a group (CSV) |
| `med_render` | PNG image with all the viewer controls (any cut plane, threshold, background…), or from a saved view |
| `med_figure` | journal figure (PDF/PNG/recipe), from parameters or from a recipe |
| `med_view` | opens the interactive viewer for the user |
| `med_to_vtu` | `.pvd` + `.vtu` series for a ParaView without a MED reader |

Statistics, extractions and histories use the Gauss points themselves. Images paint one value per element. **Numbers you report should come from `med_stats`, `med_extract` or `med_line`, not from colors.**

The tool descriptions are in English. Option values also accept their Spanish or French labels, e.g. `clip_mode="slice"`, `"Sección"` or `"Section"`. For files with several meshes, the tools accept `mesh=`.

## Outputs and settings

Aster View **never modifies `.med` files**. Everything it writes goes to `<output>/<med name>/`: screenshots, CSV files, figures, saved views (`vistas/`) and VTU files.

`<output>` is, in this order of priority:
1. the environment variable `ASTER_VIEW_OUT`;
2. `"output_dir"` in `~/.config/aster-view/config.json`;
3. `~/aster_view_output`.

The same config file stores the language chosen in the viewer:

```json
{ "language": "en", "output_dir": "~/results/aster_view" }
```

The language is chosen in this order: `--lang`, then the last one chosen in the viewer, then the environment variable `ASTER_VIEW_LANG`, then the system language, then English.

## How it is verified

- **Exact solution** (`tests/test_reader.py`, runs in CI). On the example tube, against Lamé:
  - σr at the 7 776 Gauss points within 0.6 % of the pressure;
  - σθ within 0.25 %;
  - σz ≈ 0;
  - radial displacement within 4·10⁻⁶ (relative);
  - fields at t = 0.5 exactly half of t = 1.
- **Against MEDCoupling 9.15**, on production code_aster 17.4 files: SIEF_ELGA on HEXA20 identical, Gauss point coordinates within 2·10⁻¹⁵, and a profiled DEPL field (model restricted with `GROUP_MA`) with the same NaN and identical values. `tests/ref_medcoupling_docker.py` repeats the comparison on your own files inside the code_aster Docker image.
- **Against an independent post-processing script**: on a production HEXA20 model, the cylindrical stress components reproduced 24 averaged values computed with MEDCoupling, with a maximum difference of 3·10⁻¹⁴ MPa.
- **ELNO, 2D and several meshes** (`tests/test_formats.py`, small code_aster files in `tests/data`):
  - `SIGM_ELNO` averaged over the elements around each node equals code_aster's `SIGM_NOEU` exactly, so every ELNO value sits on its node;
  - von Mises from the 4 stress components of 2D models equals code_aster's `SIEQ_ELGA` (QUAD8 and TRIA6, to 1e-13);
  - an axisymmetric tube matches Lamé within 0.3 % of the pressure;
  - a file with a 3D and a 2D mesh is read field by field on the right mesh.
- **Viewer and MCP server**: `pytest` covers off-screen rendering, values per element, picking, saved views, the three languages and all MCP tools end to end over stdio.

## Limitations

- The colors of a Gauss-point field are one value per element (mean, min, max or max |value|), not an extrapolation to the nodes.
- There are no isolines (Contour), vector glyphs, axes grid or side-by-side views yet.
- For pyramids (PY5/P13) the Gauss points are placed at the centroid.
- Tested on Linux only. Windows and macOS should work, since all dependencies have wheels, but they have not been tried.
- If the 3D view stays black (seen under Xvfb, a virtual X display), start the viewer with `VTK_DEFAULT_OPENGL_WINDOW=vtkEGLRenderWindow`, or without `DISPLAY`. It never needs a window on screen.
- Mouse-wheel zoom inside the VS Code tab has not been tested. If the view does not react, click it once to give it focus; the ± buttons and the magnifier always work.

## Development

```bash
git clone https://github.com/tin7/aster-view && cd aster-view
pip install -e ".[test]"
pytest                      # all tests (VTK renders off-screen)
pytest -m "not render"      # only reader, components and translations
```

```
aster_view/medfile.py    MED reader (h5py)               aster_view/scene.py    VTK scene and interaction
aster_view/derived.py    derived components               aster_view/viewer.py   viewer (trame)
aster_view/figure.py     journal figures                  aster_view/server.py   MCP server
aster_view/i18n.py       texts in es/en/fr, option names  aster_view/paraview_colormaps.json
examples/thick_tube/     example 1: tube under pressure (Lamé); mesh script, .comm, .export, result
examples/plate_hole/     example 2: plate with a hole, elastic-plastic
docs/make_images.py      regenerates the pictures of this README
vscode/                  VS Code extension
tests/                   pytest suite; tests/data: small code_aster files (ELNO, 2D, several meshes)
```

- **Regenerating the example** needs Docker and the official image: `examples/thick_tube/run.sh` (about 30 s).
- **Building the extension**: `cd vscode && npx @vscode/vsce package`.
- **Adding a language**: add a column to `UI` and `CHOICES` in `aster_view/i18n.py`, then `package.nls.<lang>.json` and `l10n/bundle.l10n.<lang>.json` in `vscode/`.

Bug reports and suggestions are welcome in the [issues](https://github.com/tin7/aster-view/issues). If a file does not open or looks wrong, please include `med_info` output or the error message.

## License and acknowledgements

MIT, see [LICENSE](LICENSE).

- Colormaps are sampled from ParaView 5.11 presets (BSD-3-Clause, Kitware).
- The viewer is built on [VTK](https://vtk.org) and [trame](https://kitware.github.io/trame/).
- code_aster is developed by EDF. This project is independent and not affiliated with EDF or Simvia.
