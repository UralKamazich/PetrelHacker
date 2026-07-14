const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petrel', {
  openFile: options => ipcRenderer.invoke('dialog:open-file', options || {}),
  openModel: options => ipcRenderer.invoke('dialog:open-model', options || {}),
  saveFile: options => ipcRenderer.invoke('dialog:save-file', options || {}),
  readTextFile: path => ipcRenderer.invoke('file:read-text', path),
  writeTextFile: (path, content) => ipcRenderer.invoke('file:write-text', path, content),
  run: (command, payload) => ipcRenderer.invoke('backend:run', command, payload || {}),
  onBackendEvent: callback => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('backend:event', listener);
    return () => ipcRenderer.removeListener('backend:event', listener);
  }
});
