const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("nativeDesk", {
  /** Plataforma del proceso Electron (darwin, win32, …) para el plan de automatización */
  clientPlatform: process.platform,
  screenInfo: () => ipcRenderer.invoke("desktop:screen"),
  runAction: (action) => ipcRenderer.invoke("desktop:exec", action),
});
