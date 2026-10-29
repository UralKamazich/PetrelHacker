const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petrel', {
  openFile: options => ipcRenderer.invoke('dialog:open-file', options || {}),
  openDirectory: options => ipcRenderer.invoke('dialog:open-directory', options || {}),
  openModel: options => ipcRenderer.invoke('dialog:open-model', options || {}),
  saveFile: options => ipcRenderer.invoke('dialog:save-file', options || {}),
  showWarning: options => ipcRenderer.invoke('dialog:show-warning', options || {}),
  confirm: options => ipcRenderer.invoke('dialog:confirm', options || {}),
  readTextFile: path => ipcRenderer.invoke('file:read-text', path),
  writeTextFile: (path, content) => ipcRenderer.invoke('file:write-text', path, content),
  savePngCapture: (filePath, rect) => ipcRenderer.invoke('capture:save-png', { filePath, rect }),
  copyPngCapture: rect => ipcRenderer.invoke('capture:copy-png', rect),
  loadSectionCache: cacheKey => ipcRenderer.invoke('cache:load-section', cacheKey),
  listSectionCaches: () => ipcRenderer.invoke('cache:list-sections'),
  run: (command, payload) => ipcRenderer.invoke('backend:run', command, payload || {}),
  onBackendEvent: callback => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('backend:event', listener);
    return () => ipcRenderer.removeListener('backend:event', listener);
  }
});
