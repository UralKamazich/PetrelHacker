const { app, BrowserWindow, dialog, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

let mainWindow = null;

function projectRoot() {
  return path.resolve(__dirname, '..');
}

function pythonPath() {
  const root = projectRoot();
  const candidates = [
    process.env.PETRELHACKER_PYTHON,
    path.resolve(root, '..', '.venv', 'Scripts', 'python.exe'),
    path.join(root, '.venv', 'Scripts', 'python.exe'),
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
  const candidates = [
    path.join(process.resourcesPath || '', 'backend', 'petrelhacker-backend.exe'),
    path.join(projectRoot(), 'build-electron', 'backend', 'petrelhacker-backend', 'petrelhacker-backend.exe')
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
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: options && options.filters ? options.filters : []
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
});

ipcMain.handle('dialog:open-model', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Select model folder',
    buttonLabel: 'Select model folder',
    properties: ['openDirectory']
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
});

ipcMain.handle('dialog:save-file', async (_event, options) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: options && options.defaultPath ? options.defaultPath : undefined,
    filters: options && options.filters ? options.filters : []
  });
  if (result.canceled || !result.filePath) return null;
  return result.filePath;
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
          if (mainWindow) {
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
