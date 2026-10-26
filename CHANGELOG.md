# Changelog

## 0.3.0 — 2026-10-25

### Added
- The viewer page is available in **English, Spanish and French**. A selector in the top bar
  switches the language, and the choice is remembered in `~/.config/aster-view/config.json`.
  `aster-view --lang es|en|fr` and the VS Code setting `asterView.language` override it.
- The VS Code extension is localized (en/es/fr). It finds `aster-view` in `PATH`,
  `~/.local/bin` and conda environments, and offers the settings or the installation guide when
  it cannot find it.
- Example `examples/thick_tube` (HEXA20 tube under internal pressure, Lamé solution) with the
  script and the code_aster input to regenerate it.
- `pytest` suite: exact solution, translations, off-screen rendering, viewer and MCP end to end.
  GitHub Actions runs the tests that need no rendering.
- `med_view(lang=...)`, `med_figure(recipe=...)` (the old name `receta` still works).

- New ParaView-like layout:
  - compact toolbars (color by, representation, colormap and rescale, click modes, camera, time);
  - a *Pipeline* with the file and four filters (deformed shape, threshold, cut, axial window), each with an eye to turn it on or off;
  - *Properties / Information / Values / Figure* tabs;
  - a status bar;
  - light and dark themes, remembered like the language.
- Second example `examples/plate_hole`: elastic-plastic plate with a hole, with Gauss-point internal variables and nodal fields.
- `med_line` and `med_history` plots in journal style (one column, PNG 600 dpi + PDF), with `xlabel` / `ylabel`.
- `docs/make_images.py` regenerates the README pictures from the examples.
- VS Code: if the viewer process stops, the tab says so and offers to open it again.
- The color bar can be dragged and resized with the mouse in the view, as in ParaView (near the top or bottom it turns horizontal), or placed right, left, top or bottom from the coloring properties. The placement is saved with views and figure recipes; `med_render(bar_position=...)` does the same for images.

### Fixed
- A value read with the eyedropper on the deformed shape could come out as NaN near a hole or any curved face. The point is now placed inside the cell it was taken from.
- `med_line` returned no values along a boundary face, e.g. a ligament on a symmetry plane.
- The color bar labels were cut off in narrow views (a VS Code tab); the bar is now placed at a fixed distance from the right edge.
- Numerical noise (e.g. −1e-23 on a symmetry plane) is shown as 0 in the color range.

### Changed
- The package is now called `aster-view` (module `aster_view`); the commands are unchanged.
- Option values are fixed English keys (`surface_edges`, `slice`, `absmax`, `light_gradient`…).
  Labels in any of the three languages and the v0.2 Spanish names are still accepted, including
  in saved views and figure recipes.
- MCP tool descriptions, results and error messages are in English.
- The automatic cylindrical axis goes through the common center of the nodes when they form
  rings (full, half or quarter tubes); before, it always went through the center of the box.
- Command-line options in English (`--field`, `--port`, `--no-browser`); the Spanish ones still work.
- Default output folder `~/aster_view_output`, configurable with `ASTER_VIEW_OUT` or `output_dir`.

## 0.2.0 — 2026-10-24

- Plane cuts (clip, slice, whole cells) with presets and a draggable plane.
- Journal figures (PDF/PNG 600 dpi + recipe).
- Zoom to cursor, box zoom, pan, value picking.
- Elements and nodes with their own color and size.
- Background colors, saved views, ParaView colormaps, better lighting.
- Value per element for Gauss-point fields (mean, min, max, max |value|) and Gauss-point extremes.
- VS Code custom editor ("Open With…") and status-bar button.

## 0.1.0 — 2026-10-24

- First version: MED reader, interactive viewer, MCP server, VS Code command.
