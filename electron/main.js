const { app, BrowserWindow, clipboard, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const zlib = require('zlib');
const { promisify } = require('util');
const { spawn } = require('child_process');

const gunzip = promisify(zlib.gunzip);

let mainWindow = null;
let dialogPaths = null;

function dialogPathsFile() {
  return path.join(app.getPath('userData'), 'dialog-paths.json');
}

function loadDialogPaths() {
  if (dialogPaths) return dialogPaths;
  try {
    const parsed = JSON.parse(fs.readFileSync(dialogPathsFile(), 'utf8'));
    dialogPaths = parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_error) {
    dialogPaths = {};
  }
  return dialogPaths;
}

function rememberedDirectory(key) {
  const directory = loadDialogPaths()[key];
  try {
    return directory && fs.statSync(directory).isDirectory() ? directory : undefined;
  } catch (_error) {
    return undefined;
  }
}

function saveDialogDirectory(key, selectedPath, selectedDirectory = false) {
  if (!key || !selectedPath) return;
  const directory = selectedDirectory ? selectedPath : path.dirname(selectedPath);
  try {
    if (!fs.statSync(directory).isDirectory()) return;
  } catch (_error) {
    return;
  }
  loadDialogPaths()[key] = directory;
  try {
    fs.mkdirSync(path.dirname(dialogPathsFile()), { recursive: true });
    fs.writeFileSync(dialogPathsFile(), JSON.stringify(dialogPaths, null, 2), 'utf8');
  } catch (error) {
    console.warn(`Cannot save dialog directory: ${error.message}`);
  }
}

function dialogDefaultPath(options, key, saveDialog = false) {
  const requested = options && options.defaultPath ? String(options.defaultPath) : '';
  const remembered = rememberedDirectory(key);
  if (!requested) return remembered;
  if (path.isAbsolute(requested)) return requested;
  return saveDialog && remembered ? path.join(remembered, requested) : requested;
}

function projectRoot() {
  return path.resolve(__dirname, '..');
}

function pythonPath() {
  const root = projectRoot();
  const isWin = process.platform === 'win32';
  const candidates = [
    process.env.PETRELHACKER_PYTHON,
    path.resolve(root, '..', '.venv', isWin ? 'Scripts' : 'bin', isWin ? 'python.exe' : 'python'),
    path.join(root, '.venv', isWin ? 'Scripts' : 'bin', isWin ? 'python.exe' : 'python'),
    'python'
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (candidate === 'python' || fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return 'python';
}

function backendExecutablePath() {
  if (!app.isPackaged && process.env.PETRELHACKER_USE_BUILT_BACKEND !== '1') {
    return null;
  }
  const isWin = process.platform === 'win32';
  const exeName = isWin ? 'petrelhacker-backend.exe' : 'petrelhacker-backend';
  const candidates = [
    path.join(process.resourcesPath || '', 'backend', exeName),
    path.join(projectRoot(), 'build-electron', 'backend', 'petrelhacker-backend', exeName)
  ];
  return candidates.find(candidate => candidate && fs.existsSync(candidate)) || null;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    backgroundColor: '#eef2f7',
    title: 'PetrelHacker',
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(() => {
  if (process.platform === 'darwin' && app.dock) {
    app.dock.setIcon(path.join(__dirname, 'assets', 'icon.png'));
  }
  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

ipcMain.handle('dialog:open-file', async (_event, options) => {
  const key = options && options.dialogKey ? String(options.dialogKey) : 'open-file';
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: options && options.filters ? options.filters : [],
    defaultPath: dialogDefaultPath(options, key)
  });
  if (result.canceled || !result.filePaths.length) return null;
  saveDialogDirectory(key, result.filePaths[0]);
  return result.filePaths[0];
});

ipcMain.handle('dialog:open-directory', async (_event, options) => {
  const key = options && options.dialogKey ? String(options.dialogKey) : 'open-directory';
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options && options.title ? String(options.title) : 'Select folder',
    buttonLabel: options && options.buttonLabel ? String(options.buttonLabel) : 'Select',
    properties: ['openDirectory'],
    defaultPath: dialogDefaultPath(options, key)
  });
  if (result.canceled || !result.filePaths.length) return null;
  saveDialogDirectory(key, result.filePaths[0], false);
  return result.filePaths[0];
});

ipcMain.handle('dialog:open-model', async (_event, options) => {
  const key = options && options.dialogKey ? String(options.dialogKey) : 'models';
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select model file or folder',
    buttonLabel: 'Select model',
    properties: ['openFile', 'openDirectory'],
    filters: [
      { name: 'Petrel / RESQML / Rescue', extensions: ['pet', 'epc', 'bin'] },
      { name: 'All files', extensions: ['*'] }
    ],
    defaultPath: dialogDefaultPath(options, key)
  });
  if (result.canceled || !result.filePaths.length) return null;
  saveDialogDirectory(key, result.filePaths[0], false);
  return result.filePaths[0];
});

ipcMain.handle('dialog:save-file', async (_event, options) => {
  const key = options && options.dialogKey ? String(options.dialogKey) : 'save-file';
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: dialogDefaultPath(options, key, true),
    filters: options && options.filters ? options.filters : []
  });
  if (result.canceled || !result.filePath) return null;
  saveDialogDirectory(key, result.filePath);
  return result.filePath;
});

ipcMain.handle('dialog:show-warning', async (_event, options) => {
  await dialog.showMessageBox(mainWindow, {
    type: 'warning',
    title: String(options && options.title || 'Warning'),
    message: String(options && options.message || 'Data was not saved completely.'),
    detail: String(options && options.detail || ''),
    buttons: ['OK'],
    defaultId: 0,
    noLink: true
  });
  return true;
});

ipcMain.handle('dialog:confirm', async (_event, options) => {
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'warning',
    title: String(options && options.title || 'Confirm'),
    message: String(options && options.message || ''),
    detail: String(options && options.detail || ''),
    buttons: [String(options && options.confirmLabel || 'Continue'), 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    noLink: true
  });
  return result.response === 0;
});

ipcMain.handle('file:read-text', async (_event, filePath) => {
  if (!filePath) return '';
  return fs.promises.readFile(filePath, 'utf8');
});

ipcMain.handle('file:write-text', async (_event, filePath, content) => {
  if (!filePath) return false;
  await fs.promises.writeFile(filePath, String(content == null ? '' : content), 'utf8');
  return true;
});

ipcMain.handle('capture:save-png', async (event, options) => {
  const filePath = String(options && options.filePath || '').trim();
  if (!filePath || !path.isAbsolute(filePath)) throw new Error('An absolute PNG path is required.');
  const image = await captureRendererArea(event.sender, options && options.rect);
  await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
  await fs.promises.writeFile(filePath, image.toPNG());
  return { path: filePath, size: image.getSize() };
});

ipcMain.handle('capture:copy-png', async (event, rect) => {
  const image = await captureRendererArea(event.sender, rect);
  clipboard.writeImage(image);
  return { size: image.getSize() };
});

ipcMain.handle('cache:load-section', async (_event, cacheKey) => {
  const key = String(cacheKey || '').trim();
  if (!/^[a-f0-9]{64}$/i.test(key)) throw new Error('Invalid section cache key.');
  const filePath = path.join(sectionCacheDirectory(), `${key}.json.gz`);
  const compressed = await fs.promises.readFile(filePath);
  const parsed = JSON.parse((await gunzip(compressed)).toString('utf8'));
  const result = parsed && parsed.result;
  if (!result || typeof result !== 'object') throw new Error('Invalid section cache file.');
  const now = new Date();
  fs.promises.utimes(filePath, now, now).catch(() => {});
  return result;
});

ipcMain.handle('cache:list-sections', async () => {
  let names = [];
  try {
    names = await fs.promises.readdir(sectionCacheDirectory());
  } catch (error) {
    if (error && error.code === 'ENOENT') return [];
    throw error;
  }
  const entries = [];
  for (const name of names.filter(item => /^[a-f0-9]{64}\.json\.gz$/i.test(item))) {
    try {
      const filePath = path.join(sectionCacheDirectory(), name);
      const compressed = await fs.promises.readFile(filePath);
      const parsed = JSON.parse((await gunzip(compressed)).toString('utf8'));
      const result = parsed && parsed.result;
      if (!result || typeof result !== 'object') continue;
      entries.push({
        cacheKey: name.slice(0, 64),
        modelPath: result.model_path || '',
        propertyUuid: result.property_uuid || '',
        trajectoryUuid: result.trajectory_uuid || ''
      });
    } catch (_error) {
      // A damaged cache entry must not prevent other saved sections from loading.
    }
  }
  return entries;
});

ipcMain.handle('backend:run', async (_event, command, payload) => {
  return runBackend(command, payload || {});
});

function runBackend(command, payload) {
  return new Promise((resolve, reject) => {
    const backendExe = backendExecutablePath();
    const executable = backendExe || pythonPath();
    const args = backendExe ? [command] : ['-m', 'web_backend.cli', command];
    const child = spawn(executable, args, {
      cwd: backendExe ? path.dirname(backendExe) : projectRoot(),
      env: Object.assign({}, process.env, {
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1'
      }),
      stdio: ['pipe', 'pipe', 'pipe']
    });

    let stdoutBuffer = '';
    let stderrBuffer = '';
    let lastResult = null;
    const events = [];

    child.stdout.on('data', chunk => {
      stdoutBuffer += chunk.toString('utf8');
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop();
      lines.forEach(line => {
        if (!line.trim()) return;
        try {
          const message = JSON.parse(line);
          events.push(message);
          if (message.event === 'result') {
            lastResult = message;
          }
          if (mainWindow && message.event !== 'result') {
            mainWindow.webContents.send('backend:event', Object.assign({ command }, message));
          }
        } catch (error) {
          const message = { event: 'log', command, message: line };
          events.push(message);
          if (mainWindow) mainWindow.webContents.send('backend:event', message);
        }
      });
    });

    child.stderr.on('data', chunk => {
      stderrBuffer += chunk.toString('utf8');
    });

    child.on('error', reject);

    child.on('close', code => {
      if (stdoutBuffer.trim()) {
        try {
          const message = JSON.parse(stdoutBuffer.trim());
          events.push(message);
          if (message.event === 'result') lastResult = message;
        } catch (error) {
          events.push({ event: 'log', command, message: stdoutBuffer.trim() });
        }
      }
      const errorEvent = events.find(event => event.event === 'error');
      if (code !== 0 || errorEvent) {
        const message = errorEvent ? errorEvent.message : `Backend command failed with code ${code}`;
        const details = errorEvent ? errorEvent.details : stderrBuffer;
        reject(new Error(details ? `${message}\n${details}` : message));
        return;
      }
      resolve(lastResult || { event: 'result' });
    });

    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
  });
}

async function captureRendererArea(webContents, rawRect) {
  const rect = normalizeCaptureRect(rawRect);
  const image = await webContents.capturePage(rect);
  if (image.isEmpty()) throw new Error('The section image is empty.');
  return image;
}

function normalizeCaptureRect(rawRect) {
  const x = Math.max(0, Math.floor(Number(rawRect && rawRect.x) || 0));
  const y = Math.max(0, Math.floor(Number(rawRect && rawRect.y) || 0));
  const width = Math.floor(Number(rawRect && rawRect.width) || 0);
  const height = Math.floor(Number(rawRect && rawRect.height) || 0);
  if (width < 1 || height < 1) throw new Error('The section area is not visible.');
  return { x, y, width, height };
}

function sectionCacheDirectory() {
  if (process.platform === 'darwin') return path.join(os.homedir(), 'Library', 'Caches', 'PetrelHacker', 'section-cache');
  if (process.platform === 'win32') {
    return path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'PetrelHacker', 'section-cache');
  }
  return path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'petrelhacker', 'section-cache');
}
