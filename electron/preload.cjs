const { contextBridge, ipcRenderer } = require("electron");

// The only things the page may ask the desktop app for.
contextBridge.exposeInMainWorld("karyakarta", {
  getConnection: () => ipcRenderer.invoke("karyakarta:connection"),
  openExternal: (url) => ipcRenderer.invoke("karyakarta:open-external", url),
});
