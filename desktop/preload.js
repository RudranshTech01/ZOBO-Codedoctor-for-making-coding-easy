const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('codeDoctorDesktop', {
  onRequestScan: (callback) => ipcRenderer.on('request-scan', () => callback()),
  captureWithPermission: () => ipcRenderer.invoke('capture-with-permission')
});
