// Aster View: opens .med results in the interactive viewer (aster-view, trame).
// Rendering is done by the server (VTK) and images arrive: no WebGL needed in VSCode.
// Ways to open it: right-click in the explorer or on the tab, button in the title bar
// of the vs-code-aster (Simvia) mesh viewer, "Open With…" → Aster View, or the
// status bar button. The texts of this extension follow the VSCode language
// (package.nls.*.json and l10n/); the viewer page, the asterView.language setting.
const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const VIEW_TYPE = 'asterView.editor';
const MED_RE = /\.(r?med|mmed)$/i;
const INSTALL_URL = 'https://github.com/tin7/aster-view#installation';
const viewers = new Map(); // .med path -> { proc, url, refs }
const panels = new Map();  // .med path -> tabs open with that viewer
const t = vscode.l10n.t;
let out;

class NotFound extends Error {}

function waitPort(port, ms) {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const s = net.connect(port, '127.0.0.1');
      s.once('connect', () => { s.destroy(); resolve(); });
      s.once('error', () => {
        s.destroy();
        if (Date.now() - t0 > ms) reject(new Error(t('the viewer did not respond in time')));
        else setTimeout(tryOnce, 300);
      });
    };
    tryOnce();
  });
}

// The executable: the setting if it is a path; otherwise search PATH, ~/.local/bin and the
// conda environments (VSCode opened from the desktop usually has no environment activated).
function findExecutable() {
  const setting = (vscode.workspace.getConfiguration('asterView').get('executable') || '').trim();
  if (setting && setting !== 'aster-view') return setting;
  const win = process.platform === 'win32';
  const names = win ? ['aster-view.exe', 'aster-view.cmd'] : ['aster-view'];
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  const home = os.homedir();
  dirs.push(path.join(home, '.local', 'bin'));
  // environment folders (venv and conda); the README suggests ~/venvs/aster-view
  for (const base of ['venvs', '.venvs', '.virtualenvs', 'anaconda3/envs', 'miniconda3/envs', 'miniforge3/envs',
                      'mambaforge/envs', 'micromamba/envs', '.conda/envs']) {
    let list = [];
    try { list = fs.readdirSync(path.join(home, base)); } catch (e) { /* no existe */ }
    for (const e of list) dirs.push(path.join(home, base, e, win ? 'Scripts' : 'bin'));
  }
  for (const base of ['venv', '.venv', 'anaconda3', 'miniconda3', 'miniforge3', 'mambaforge', 'micromamba', '.conda']) {
    dirs.push(path.join(home, base, win ? 'Scripts' : 'bin'));
  }
  for (const d of dirs) {
    for (const n of names) {
      const p = path.join(d, n);
      try { if (fs.statSync(p).isFile()) return p; } catch (e) { /* sigue */ }
    }
  }
  return null;
}

// Starts aster-view for the file (or reuses the one already running) and returns its URL.
function launch(file) {
  const old = viewers.get(file);
  if (old && old.proc.exitCode === null) return Promise.resolve(old.url);
  const exe = findExecutable();
  if (!exe) return Promise.reject(new NotFound(
    t('The aster-view command was not found. Install the Python package (see the README) or set "asterView.executable" to its full path.')));
  const args = [file, '--no-browser'];
  const env = { ...process.env };
  const lang = vscode.workspace.getConfiguration('asterView').get('language') || 'auto';
  if (lang !== 'auto') args.push('--lang', lang);
  else env.ASTER_VIEW_LANG = vscode.env.language; // only if the viewer has no remembered language
  return new Promise((resolve, reject) => {
    const proc = cp.spawn(exe, args, { stdio: ['ignore', 'pipe', 'pipe'], env });
    let buf = '';
    let done = false;
    const timer = setTimeout(() => {
      if (!done) { done = true; proc.kill(); reject(new Error(t('it took more than 2 min to start'))); }
    }, 120000);
    proc.stdout.on('data', d => {
      out.append(d.toString());
      buf += d.toString();
      const m = buf.match(/ASTER_VIEW_URL (http:\/\/localhost:(\d+)\/)/);
      if (m && !done) {
        waitPort(Number(m[2]), 90000).then(() => {
          done = true;
          clearTimeout(timer);
          viewers.set(file, { proc, url: m[1], refs: 0 });
          resolve(m[1]);
        }, e => { done = true; proc.kill(); reject(e); });
      }
    });
    proc.stderr.on('data', d => out.append(d.toString()));
    proc.on('error', e => {
      if (!done) { done = true; clearTimeout(timer); reject(new Error(t('could not run {0}: {1}', exe, e.message))); }
    });
    proc.on('exit', code => {
      viewers.delete(file);
      if (!done) { done = true; clearTimeout(timer); reject(new Error(t('aster-view exited (code {0})', String(code)))); return; }
      // the viewer died with the tab open: notice and a button to open it again
      out.appendLine(`aster-view (${path.basename(file)}) exited, code ${code}`);
      for (const panel of panels.get(file) || []) panel.webview.html = stoppedHtml();
    });
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function pageHtml(body, csp) {
  return `<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; ${csp || ''}">
<style>html,body{margin:0;padding:0;height:100%;overflow:hidden;font-family:var(--vscode-font-family);color:var(--vscode-foreground)}
iframe{border:0;width:100%;height:100vh;display:block}.msg{padding:24px}
button{margin-left:10px;padding:4px 12px;border:none;border-radius:2px;cursor:pointer;
background:var(--vscode-button-background);color:var(--vscode-button-foreground)}</style></head><body>${body}</body></html>`;
}

async function reportError(e) {
  out.appendLine(`Aster View: ${e.message}`);
  if (e instanceof NotFound) {
    const open = t('Open settings');
    const guide = t('Installation guide');
    const pick = await vscode.window.showErrorMessage(`Aster View: ${e.message}`, open, guide);
    if (pick === open) vscode.commands.executeCommand('workbench.action.openSettings', 'asterView.executable');
    if (pick === guide) vscode.env.openExternal(vscode.Uri.parse(INSTALL_URL));
  } else {
    vscode.window.showErrorMessage(`Aster View: ${e.message}. ${t('Details in the "Aster View" output.')}`);
    out.show(true);
  }
}

function stoppedHtml() {
  return pageHtml(`<div class="msg">${escapeHtml(t('The viewer stopped.'))}
<button onclick="acquireVsCodeApi().postMessage('reload')">${escapeHtml(t('Open it again'))}</button></div>`,
    "script-src 'unsafe-inline';");
}

// Custom editor: the tab shows the viewer (iframe to the local aster-view server).
class AsterViewEditor {
  openCustomDocument(uri) { return { uri, dispose() {} }; }

  async resolveCustomEditor(document, panel) {
    const file = document.uri.fsPath;
    panel.webview.options = { enableScripts: true };
    if (!panels.has(file)) panels.set(file, new Set());
    panels.get(file).add(panel);
    panel.webview.onDidReceiveMessage(m => { if (m === 'reload') this.load(panel, file); });
    panel.onDidDispose(() => {
      panels.get(file).delete(panel);
      const v = viewers.get(file);
      if (v && --v.refs <= 0) { v.proc.kill(); viewers.delete(file); }
    });
    await this.load(panel, file);
  }

  async load(panel, file) {
    panel.webview.html = pageHtml(`<div class="msg">${escapeHtml(t('Aster View: opening {0}…', path.basename(file)))}</div>`);
    try {
      const url = await launch(file);
      const v = viewers.get(file);
      if (v) v.refs += 1;
      const ext = (await vscode.env.asExternalUri(vscode.Uri.parse(url))).toString();
      const origin = ext.replace(/\/$/, '');
      panel.webview.html = pageHtml(`<iframe src="${ext}" allow="clipboard-read; clipboard-write"></iframe>`,
        `frame-src ${origin} http://localhost:* http://127.0.0.1:*;`);
      out.appendLine(`${path.basename(file)} -> ${url}`);
    } catch (e) {
      panel.webview.html = pageHtml(`<div class="msg">Aster View: ${escapeHtml(e.message)}</div>`);
      reportError(e);
    }
  }
}

function activeMedUri() {
  const tab = vscode.window.tabGroups.activeTabGroup.activeTab;
  const input = tab && tab.input;
  if (!input || !input.uri || !MED_RE.test(input.uri.fsPath)) return undefined;
  if (input.viewType === VIEW_TYPE) return undefined; // already in Aster View
  return input.uri;
}

async function openUri(uri) {
  const where = vscode.workspace.getConfiguration('asterView').get('openIn');
  if (where === 'browser' || where === 'navegador') { // 'navegador': v0.2 name
    try {
      const url = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: t('Aster View: opening {0}…', path.basename(uri.fsPath)) },
        () => launch(uri.fsPath));
      vscode.env.openExternal(vscode.Uri.parse(url));
    } catch (e) {
      reportError(e);
    }
  } else {
    await vscode.commands.executeCommand('vscode.openWith', uri, VIEW_TYPE, { preview: false });
  }
}

function activate(context) {
  out = vscode.window.createOutputChannel('Aster View');
  context.subscriptions.push(out);

  context.subscriptions.push(vscode.window.registerCustomEditorProvider(VIEW_TYPE, new AsterViewEditor(), {
    webviewOptions: { retainContextWhenHidden: true },
    supportsMultipleEditorsPerDocument: false,
  }));

  context.subscriptions.push(vscode.commands.registerCommand('asterView.open', async (uri) => {
    if (!(uri instanceof vscode.Uri)) uri = activeMedUri();
    if (!uri) {
      const pick = await vscode.window.showOpenDialog({ filters: { [t('MED results')]: ['med', 'rmed', 'mmed'] } });
      uri = pick && pick[0];
    }
    if (uri) await openUri(uri);
  }));

  context.subscriptions.push(vscode.commands.registerCommand('asterView.stopAll', () => {
    for (const { proc } of viewers.values()) proc.kill();
    viewers.clear();
  }));

  // status bar button while a .med is open (in the mesh viewer or as text)
  const sb = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  sb.text = '$(graph) Aster View';
  sb.tooltip = t('Open this result in Aster View (fields, time steps, cuts, figures)');
  sb.command = 'asterView.open';
  context.subscriptions.push(sb);
  const refresh = () => (activeMedUri() ? sb.show() : sb.hide());
  context.subscriptions.push(vscode.window.tabGroups.onDidChangeTabs(refresh));
  context.subscriptions.push(vscode.window.tabGroups.onDidChangeTabGroups(refresh));
  refresh();
}

function deactivate() {
  for (const { proc } of viewers.values()) proc.kill();
}

module.exports = { activate, deactivate };
