import { contextBridge, ipcRenderer, webUtils } from 'electron'

type Listener<T = any> = (payload: T) => void

const api = {
  request: <T = any>(method: string, params: Record<string, any> = {}): Promise<T> =>
    ipcRenderer.invoke('engine:request', { method, params: JSON.parse(JSON.stringify(params ?? {})) }),
  resolveAsset: (assetId: string) => ipcRenderer.invoke('media:resolveAsset', { assetId }),
  onEngineEvent: (listener: Listener) => {
    const wrapped = (_event: Electron.IpcRendererEvent, payload: any) => listener(payload)
    ipcRenderer.on('engine:event', wrapped)
    return () => ipcRenderer.removeListener('engine:event', wrapped)
  },
  onEngineStatus: (listener: Listener) => {
    const wrapped = (_event: Electron.IpcRendererEvent, payload: any) => listener(payload)
    ipcRenderer.on('engine:status', wrapped)
    return () => ipcRenderer.removeListener('engine:status', wrapped)
  },
  onEngineFatal: (listener: Listener) => {
    const wrapped = (_event: Electron.IpcRendererEvent, payload: any) => listener(payload)
    ipcRenderer.on('engine:fatal', wrapped)
    return () => ipcRenderer.removeListener('engine:fatal', wrapped)
  },
  engineStatus: () => ipcRenderer.invoke('engine:status'),
  restartEngine: () => ipcRenderer.invoke('engine:restart'),
  logTail: () => ipcRenderer.invoke('engine:logTail'),
  openMediaDialog: () => ipcRenderer.invoke('dialog:openMedia'),
  openCookiesDialog: () => ipcRenderer.invoke('dialog:openCookies'),
  registerDroppedFile: async (file: File): Promise<string | null> => {
    const path = webUtils.getPathForFile(file)
    if (!path) return null
    return ipcRenderer.invoke('files:registerDropped', { path })
  },
  chooseFolder: () => ipcRenderer.invoke('dialog:chooseFolder'),
  openExternal: (url: string) => ipcRenderer.invoke('app:openExternal', { url }),
  showItemInFolder: (path: string) => ipcRenderer.invoke('app:showItemInFolder', { path }),
  openPath: (path: string) => ipcRenderer.invoke('app:openPath', { path }),
  appInfo: () => ipcRenderer.invoke('app:info'),
  secretStatus: () => ipcRenderer.invoke('secrets:status'),
  setSecret: (profileId: string, apiKey: string, allowWeak = false) =>
    ipcRenderer.invoke('secrets:set', { profileId, apiKey, allowWeak }),
  deleteSecret: (profileId: string) => ipcRenderer.invoke('secrets:delete', { profileId })
}

contextBridge.exposeInMainWorld('clipwright', api)

export type ClipwrightApi = typeof api
