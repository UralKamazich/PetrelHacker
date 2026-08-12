const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

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
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(createWindow);

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

ipcMain.handle('file:read-text', async (_event, filePath) => {
  if (!filePath) return '';
  return fs.promises.readFile(filePath, 'utf8');
});

ipcMain.handle('file:write-text', async (_event, filePath, content) => {
  if (!filePath) return false;
  await fs.promises.writeFile(filePath, String(content == null ? '' : content), 'utf8');
  return true;
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
