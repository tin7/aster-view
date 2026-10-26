# Aster View for VS Code

Opens **code_aster MED results** (`.med`, `.rmed`, `.mmed`) in the interactive
[Aster View](https://github.com/tin7/aster-view) viewer, inside a VS Code tab. The viewer shows
fields and time steps, the deformed shape, plane cuts, values on click, Gauss-point extremes and
journal figures. Its page is available in English, Spanish and French.

![Aster View in VS Code](https://raw.githubusercontent.com/tin7/aster-view/main/docs/img/viewer.png)

## Requirements

The viewer itself is a Python package. Install it first (Python ≥ 3.10):

```bash
python3 -m venv ~/venvs/aster-view && source ~/venvs/aster-view/bin/activate
pip install git+https://github.com/tin7/aster-view
```

The extension finds `aster-view` in `PATH`, `~/.local/bin` and conda environments. If it lives
elsewhere, set **Aster View: Executable** to its full path.

## Opening a result

- right-click the file in the explorer, or its editor tab → **Open in Aster View (results)**;
- **Open With… → Aster View (results)** (from there it can become the default editor for `*.med`);
- the **Aster View** button in the status bar while a `.med` file is open;
- the chart button in the title bar of the mesh viewer of
  [VS Code Aster](https://github.com/simvia-tech/vs-code-aster), which shows meshes and groups.
  Aster View adds the results on top of it.

## Settings

| setting | default | |
|---|---|---|
| `asterView.executable` | `aster-view` | the command, or its full path |
| `asterView.openIn` | `vscode` | `vscode` (tab) or `browser` |
| `asterView.language` | `auto` | `auto`, `en`, `es` or `fr`; `auto` = the language last chosen in the viewer, or the VS Code language the first time |

The menus and messages of the extension follow the VS Code display language (English, Spanish or French).

More: [documentation](https://github.com/tin7/aster-view#readme) ·
[issues](https://github.com/tin7/aster-view/issues) · MIT license.
