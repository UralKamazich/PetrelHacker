const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('petrel', {
  openFile: options => ipcRenderer.invoke('dialog:open-file', options || {}),
  openModel: () => ipcRenderer.invoke('dialog:open-model'),
  saveFile: options => ipcRenderer.invoke('dialog:save-file', options || {}),
  run: (command, payload) => ipcRenderer.invoke('backend:run', command, payload || {}),
  onBackendEvent: callback => {
    const listener = (_event, message) => callback(message);
    ipcRenderer.on('backend:event', listener);
    return () => ipcRenderer.removeListener('backend:event', listener);
  }
});
