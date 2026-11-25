import { app, dialog, ipcMain, shell, BrowserWindow } from 'electron'
import { existsSync, mkdirSync, statSync } from 'node:fs'
import { isAbsolute, relative, resolve } from 'node:path'
import { z } from 'zod'
import type { EngineClient } from './engine'
import { EngineError } from './engine'
import type { SecretStore } from './secrets'
import { registerMedia } from './media'

const ALLOWED_METHODS = new Set([
  'engine.hello', 'engine.ping', 'engine.shutdown',
  'project.create', 'project.list', 'project.open', 'project.delete', 'project.rename',
  'preset.list', 'preset.save', 'preset.delete',
  'source.import_file', 'source.import_url', 'source.get', 'source.probe', 'source.preview',
  'source.fetch_preview', 'source.set_authorization', 'media.resolve',
  'transcription.start', 'transcript.get', 'transcript.list',
  'analysis.start', 'analysis.estimate', 'analysis.list',
  'candidates.list', 'candidates.update_bounds', 'candidates.revisions', 'candidates.undo', 'candidates.rename', 'candidates.set_status',
  'selection.set', 'selection.list', 'edit.get', 'edit.set', 'metadata.generate',
  'render.start', 'render.queue',
  'provider.list', 'provider.save', 'provider.delete', 'provider.test', 'provider.list_models',
  'settings.get', 'settings.set', 'hardware.detect',
  'models.list', 'models.download', 'models.verify', 'models.delete',
  'binaries.status', 'binaries.update', 'diagnostics.export',
  'jobs.list', 'jobs.get', 'jobs.cancel', 'jobs.resume',
  'privacy.log', 'privacy.clear'
])

const KEY_METHODS = new Set(['analysis.start', 'transcription.start', 'provider.test', 'provider.list_models', 'metadata.generate', 'jobs.resume'])

const engineRequestSchema = z.object({
  method: z.string().min(1).max(80),
  params: z.record(z.string(), z.unknown()).default({})
})

const chosenFiles = new Set<string>()
const E2E = process.env.CLIPWRIGHT_E2E === '1'
const chosenFolders = new Set<string>()

function isInside(child: string, parent: string): boolean {
  const rel = relative(resolve(parent), resolve(child))
  return rel === '' || (!rel.startsWith('..') && !isAbsolute(rel))
}

function stripLocalPath(source: any): any {
  if (!source) return source
  if (source.localPath) {
    source.mediaUrl = registerMedia(source.localPath)
    delete source.localPath
  }
  return source
}

function decorate(method: string, result: any): any {
  if (!result || typeof result !== 'object') return result
  if (result.source) stripLocalPath(result.source)
  if (result.project?.sources) {
    for (const source of result.project.sources) stripLocalPath(source)
  }
  if (result.sources) for (const source of result.sources) stripLocalPath(source)
  if (Array.isArray(result.assets)) {
    for (const asset of result.assets) {
      if (asset.path) {
        asset.mediaUrl = registerMedia(asset.path, asset.mime)
        delete asset.path
      }
    }
  }
  if (result.path && (method === 'source.preview' || method === 'source.fetch_preview')) {
    result.mediaUrl = registerMedia(result.path)
    delete result.path
  }
  if (method === 'source.fetch_preview' && result.mediaUrl && result.startS != null && result.endS != null) {
    result.fragment = `#t=${result.startS},${result.endS}`
  }
  return result
}

async function profileIdFor(engine: EngineClient, method: string, params: Record<string, any>): Promise<string | undefined> {
  if (params.providerProfileId) return String(params.providerProfileId)
  if (method === 'provider.test' || method === 'provider.list_models') return params.profileId ? String(params.profileId) : undefined
  if (method === 'jobs.resume') {
    try {
      const job = await engine.request('jobs.get', { jobId: params.jobId })
      return job?.job?.params?.providerProfileId
    } catch {
      return undefined
    }
  }
  return undefined
}

export function registerIpc(engine: EngineClient, secrets: SecretStore, getWindow: () => BrowserWindow | null) {
  function trusted(event: Electron.IpcMainInvokeEvent): boolean {
    const win = getWindow()
    return Boolean(
      win &&
        !win.isDestroyed() &&
        event.sender.id === win.webContents.id &&
        event.senderFrame === win.webContents.mainFrame
    )
  }

  function assertTrusted(event: Electron.IpcMainInvokeEvent) {
    if (!trusted(event)) throw new Error('Untrusted IPC sender')
  }

  ipcMain.handle('app:info', (event) => {
    assertTrusted(event)
    return {
    productName: 'Clipwright',
    version: app.getVersion(),
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
    platform: process.platform,
    arch: process.arch,
    isPackaged: app.isPackaged,
    userData: app.getPath('userData')
  }
  })

  ipcMain.handle('engine:status', (event) => {
    assertTrusted(event)
    return { status: engine.getStatus(), logTail: engine.getLogTail().slice(-40) }
  })
  ipcMain.handle('engine:restart', async (event) => {
    assertTrusted(event)
    await engine.restart()
    return { status: engine.getStatus(), logTail: engine.getLogTail().slice(-40) }
  })
  ipcMain.handle('engine:logTail', (event) => {
    assertTrusted(event)
    return engine.getLogTail().slice(-100)
  })

  ipcMain.handle('engine:request', async (event, raw) => {
    assertTrusted(event)
    const parsed = engineRequestSchema.safeParse(raw)
    if (!parsed.success) throw new Error('Invalid engine request')
    const { method, params } = parsed.data
    if (!ALLOWED_METHODS.has(method)) throw new Error(`Method not allowed: ${method}`)
    if (method === 'source.import_file') {
      const path = String(params.path || '')
      if (!E2E && !chosenFiles.has(path)) throw new Error('Choose the file with the file picker.')
    }
    if (method === 'render.start' && params.outputDir) {
      const dir = String(params.outputDir)
      const allowed =
        chosenFolders.has(dir) ||
        isInside(dir, app.getPath('userData')) ||
        isInside(dir, app.getPath('videos'))
      if (!E2E && !allowed) throw new Error('Choose the output folder with the folder picker.')
    }
    const secretPayload: Record<string, string> = {}
    if (KEY_METHODS.has(method)) {
      const pid = await profileIdFor(engine, method, params)
      const key = await secrets.getKey(pid)
      if (key) secretPayload.apiKey = key
    }
    try {
      const result = await engine.request(method, params, {
        timeoutMs: method === 'binaries.update' || method === 'source.fetch_preview' ? 600000 : 180000,
        secrets: Object.keys(secretPayload).length ? secretPayload : undefined
      })
      if (method === 'render.start') {
        const dir = String(params.outputDir || '')
        if (dir) chosenFolders.add(dir)
      }
      return decorate(method, result)
    } catch (error) {
      if (error instanceof EngineError) {
        return {
          __error: {
            code: error.code,
            message: error.message,
            details: error.details,
            retryable: error.retryable
          }
        }
      }
      return { __error: { code: 'IPC_FAILED', message: error instanceof Error ? error.message : String(error) } }
    }
  })

  ipcMain.handle('media:resolveAsset', async (event, raw) => {
    assertTrusted(event)
    const parsed = z.object({ assetId: z.string().min(1) }).safeParse(raw)
    if (!parsed.success) throw new Error('Invalid asset request')
    const result = await engine.request('media.resolve', { assetId: parsed.data.assetId })
    return {
      mediaUrl: registerMedia(result.path, result.mime),
      startS: result.startS,
      endS: result.endS
    }
  })

  ipcMain.handle('dialog:openMedia', async (event) => {
    assertTrusted(event)
    if (E2E && process.env.CLIPWRIGHT_E2E_OPEN_FILE) {
      const path = resolve(process.env.CLIPWRIGHT_E2E_OPEN_FILE)
      if (existsSync(path)) {
        chosenFiles.add(path)
        return { path, name: path.split(/[\\/]/).pop() }
      }
    }
    const win = getWindow()
    const result = await dialog.showOpenDialog(win!, {
      title: 'Choose a video or audio file',
      properties: ['openFile'],
      filters: [
        { name: 'Video', extensions: ['mp4', 'mkv', 'webm', 'mov', 'm4v', 'avi'] },
        { name: 'Audio', extensions: ['mp3', 'm4a', 'wav', 'flac', 'aac', 'ogg'] },
        { name: 'All files', extensions: ['*'] }
      ]
    })
    if (result.canceled || !result.filePaths[0]) return null
    const path = result.filePaths[0]
    chosenFiles.add(path)
    return { path, name: path.split(/[\\/]/).pop() }
  })

  ipcMain.handle('dialog:openCookies', async (event) => {
    assertTrusted(event)
    const win = getWindow()
    const result = await dialog.showOpenDialog(win!, {
      title: 'Choose a Netscape cookies.txt file',
      properties: ['openFile'],
      filters: [{ name: 'Cookies text', extensions: ['txt'] }, { name: 'All files', extensions: ['*'] }]
    })
    if (result.canceled || !result.filePaths[0]) return null
    const path = result.filePaths[0]
    return { path, name: path.split(/[\\/]/).pop() }
  })

  ipcMain.handle('files:registerDropped', (event, raw) => {
    assertTrusted(event)
    const parsed = z.object({ path: z.string().min(1) }).safeParse(raw)
    if (!parsed.success) return null
    const path = resolve(parsed.data.path)
    try {
      if (!statSync(path).isFile()) return null
    } catch {
      return null
    }
    chosenFiles.add(path)
    return path
  })

  ipcMain.handle('dialog:chooseFolder', async (event) => {
    assertTrusted(event)
    if (E2E && process.env.CLIPWRIGHT_E2E_OUTPUT_DIR) {
      const path = resolve(process.env.CLIPWRIGHT_E2E_OUTPUT_DIR)
      mkdirSync(path, { recursive: true })
      chosenFolders.add(path)
      return { path }
    }
    const win = getWindow()
    const result = await dialog.showOpenDialog(win!, {
      title: 'Choose an output folder',
      properties: ['openDirectory', 'createDirectory']
    })
    if (result.canceled || !result.filePaths[0]) return null
    const path = result.filePaths[0]
    chosenFolders.add(path)
    return { path }
  })

  ipcMain.handle('app:openExternal', async (event, raw) => {
    assertTrusted(event)
    const parsed = z.object({ url: z.string().url().max(2048) }).safeParse(raw)
    if (!parsed.success) return false
    const url = new URL(parsed.data.url)
    if (url.protocol !== 'https:' && url.protocol !== 'mailto:') return false
    await shell.openExternal(url.toString())
    return true
  })

  ipcMain.handle('app:showItemInFolder', async (event, raw) => {
    assertTrusted(event)
    const parsed = z.object({ path: z.string().min(1) }).safeParse(raw)
    if (!parsed.success) return false
    const path = resolve(parsed.data.path)
    if (!existsSync(path) || !statSync(path).isFile()) return false
    const allowed = [...chosenFolders].some((dir) => isInside(path, dir)) || isInside(path, app.getPath('userData'))
    if (!E2E && !allowed) return false
    shell.showItemInFolder(path)
    return true
  })

  ipcMain.handle('app:openPath', async (event, raw) => {
    assertTrusted(event)
    const parsed = z.object({ path: z.string().min(1) }).safeParse(raw)
    if (!parsed.success) return false
    const path = resolve(parsed.data.path)
    if (!existsSync(path)) return false
    if (!isInside(path, app.getPath('userData'))) return false
    await shell.openPath(path)
    return true
  })

  ipcMain.handle('secrets:status', (event) => {
    assertTrusted(event)
    return secrets.status()
  })
  ipcMain.handle('secrets:set', async (event, raw) => {
    assertTrusted(event)
    const parsed = z
      .object({ profileId: z.string().min(1), apiKey: z.string().max(4096), allowWeak: z.boolean().default(false) })
      .safeParse(raw)
    if (!parsed.success) throw new Error('Invalid secret request')
    return secrets.setKey(parsed.data.profileId, parsed.data.apiKey, parsed.data.allowWeak)
  })
  ipcMain.handle('secrets:delete', async (event, raw) => {
    assertTrusted(event)
    const parsed = z.object({ profileId: z.string().min(1) }).safeParse(raw)
    if (!parsed.success) throw new Error('Invalid secret request')
    await secrets.deleteKey(parsed.data.profileId)
    return { ok: true }
  })
}
