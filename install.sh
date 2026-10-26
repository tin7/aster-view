#!/bin/sh
# Installs Aster View on Ubuntu/Debian in one go:
#   wget -qO- https://raw.githubusercontent.com/tin7/aster-view/main/install.sh | sh
# 1. system packages (asks for sudo): Python with venv and pip, and the libraries VTK needs;
# 2. a virtual environment in ~/venvs/aster-view with the package (no git needed);
# 3. the commands aster-view and aster-mcp in ~/.local/bin;
# 4. the VS Code extension, if VS Code is installed.
# Change the place of the environment with ASTER_VIEW_VENV=/some/dir before "sh".
set -e
# shortcut: fixed version, bump it with each release
VERSION=${ASTER_VIEW_VERSION:-0.4.1}
VENV=${ASTER_VIEW_VENV:-$HOME/venvs/aster-view}
REPO=https://github.com/tin7/aster-view

if command -v apt-get >/dev/null 2>&1; then
    SUDO=""
    [ "$(id -u)" -ne 0 ] && SUDO=sudo
    echo "== System packages: python3, python3-venv, python3-pip and OpenGL libraries for VTK"
    $SUDO apt-get update -qq
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq python3 python3-venv python3-pip libgl1 libegl1 libxrender1 >/dev/null
else
    echo "== Not a Debian/Ubuntu system: make sure python3 (>= 3.10) with venv and pip is installed."
fi

echo "== Virtual environment: $VENV"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
echo "== Python package aster-view $VERSION (a few minutes: VTK and trame are large)"
"$VENV/bin/python" -m pip install -q "$REPO/archive/refs/tags/v$VERSION.zip"

mkdir -p "$HOME/.local/bin"
ln -sf "$VENV/bin/aster-view" "$HOME/.local/bin/aster-view"
ln -sf "$VENV/bin/aster-mcp" "$HOME/.local/bin/aster-mcp"

if command -v code >/dev/null 2>&1; then
    echo "== VS Code extension $VERSION"
    TMP=$(mktemp -d)
    "$VENV/bin/python" -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
        "$REPO/releases/download/v$VERSION/aster-view-$VERSION.vsix" "$TMP/aster-view.vsix"
    code --install-extension "$TMP/aster-view.vsix" --force
    rm -rf "$TMP"
    echo "   In VS Code: Ctrl+Shift+P -> 'Developer: Reload Window'."
else
    echo "== VS Code not found: the extension was not installed (see the README to install it later)."
fi

"$VENV/bin/aster-view" --help >/dev/null
echo
echo "Done. Open a result with:  aster-view file.med"
echo "If 'aster-view' is not found, open a new terminal (~/.local/bin is added to PATH at login),"
echo "or run it as $VENV/bin/aster-view."
echo "MCP server for Claude Code:  claude mcp add --scope user aster-med -- $VENV/bin/aster-mcp"
