/// <reference types="vite/client" />
/// <reference types="svelte" />

import type { UpdateState } from '$shared/updates'

interface ClipwrightBridge {
  request<T = any>(method: string, params?: Record<string, any>): Promise<T>
  resolveAsset(assetId: string): Promise<{ mediaUrl: string; startS?: number; endS?: number }>
  onEngineEvent(listener: (payload: any) => void): () => void
  onEngineStatus(listener: (payload: any) => void): () => void
  onEngineFatal(listener: (payload: any) => void): () => void
  engineStatus(): Promise<{ status: string; logTail: string[] }>
  logTail(): Promise<string[]>
  openMediaDialog(): Promise<{ path: string; name: string } | null>
  openCookiesDialog(): Promise<{ path: string; name: string } | null>
  chooseFolder(): Promise<{ path: string } | null>
  openExternal(url: string): Promise<boolean>
  showItemInFolder(path: string): Promise<boolean>
  openPath(path: string): Promise<boolean>
  appInfo(): Promise<any>
  updateState(): Promise<UpdateState>
  checkForUpdates(force?: boolean): Promise<UpdateState>
  onUpdateStatus(listener: (state: UpdateState) => void): () => void
  secretStatus(): Promise<any>
  setSecret(profileId: string, apiKey: string, allowWeak?: boolean): Promise<any>
  deleteSecret(profileId: string): Promise<any>
}

declare global {
  interface Window {
    clipwright: ClipwrightBridge
  }
}

export {}
