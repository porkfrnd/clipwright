import { app, BrowserWindow, Menu, session, shell } from 'electron'
import { join } from 'node:path'
import { appendFileSync, existsSync, mkdirSync } from 'node:fs'
import { EngineClient } from './engine'
import { SecretStore } from './secrets'
import { installMediaProtocol, registerScheme } from './media'
import { registerIpc } from './ipc'
import { PRODUCT_NAME } from '../shared/brand'

registerScheme()
app.enableSandbox()
app.setName(PRODUCT_NAME)
if (process.env.CLIPWRIGHT_USER_DATA) app.setPath('userData', process.env.CLIPWRIGHT_USER_DATA)

let mainWindow: BrowserWindow | null = null
let engine: EngineClient
let secretStore: SecretStore
let quitting = false
let pendingEvents: any[] = []
let rendererReloads = 0
let rendererReloadReset: NodeJS.Timeout | null = null

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
}

function mainLog(message: string) {
  try {
    const dir = app.getPath('logs')
    mkdirSync(dir, { recursive: true })
    appendFileSync(join(dir, 'main.log'), `${new Date().toISOString()} ${message}\n`)
  } catch {
    // logging must never take the app down
  }
}

function send(channel: string, payload: any) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload)
  } else {
    pendingEvents.push({ channel, payload })
    if (pendingEvents.length > 100) pendingEvents.shift()
  }
}

function installCsp() {
  const csp = [
    "default-src 'self'",
    "script-src 'self' file:",
    "style-src 'self' 'unsafe-inline' file:",
    "img-src 'self' data: media: file:",
    "media-src 'self' media: blob:",
    "font-src 'self' data: file:",
    app.isPackaged
      ? "connect-src 'self'"
      : "connect-src 'self' ws://localhost:* http://localhost:*",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "frame-ancestors 'none'"
  ].join('; ')
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [csp]
      }
    })
  })
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false))
  session.defaultSession.setPermissionCheckHandler(() => false)
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1120,
    minHeight: 720,
    show: false,
    backgroundColor: '#0b0810',
    title: PRODUCT_NAME,
    autoHideMenuBar: process.platform !== 'darwin',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: true,
      allowRunningInsecureContent: false,
      spellcheck: false,
      devTools: !app.isPackaged || process.env.CLIPWRIGHT_DEVTOOLS === '1'
    }
  })

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
    for (const item of pendingEvents.splice(0)) send(item.channel, item.payload)
  })

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const current = mainWindow?.webContents.getURL() || ''
    if (url !== current) event.preventDefault()
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('mailto:')) {
      shell.openExternal(url).catch(() => undefined)
    }
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-attach-webview', (event) => event.preventDefault())
  mainWindow.webContents.on('unresponsive', () => mainLog('renderer marked unresponsive'))
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    mainLog(`renderer process gone: reason=${details.reason} exitCode=${details.exitCode}`)
    if (quitting || !mainWindow || mainWindow.isDestroyed()) return
    if (rendererReloads >= 2) return
    rendererReloads += 1
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.reload()
    }, 500)
  })
  mainWindow.webContents.on('did-finish-load', () => {
    if (rendererReloadReset) clearTimeout(rendererReloadReset)
    rendererReloadReset = setTimeout(() => {
      rendererReloads = 0
    }, 60000)
  })

  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function buildMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }
      ]
    },
    {
      label: 'View',
      submenu: [
        ...(app.isPackaged ? [] : [{ role: 'reload' as const }, { role: 'toggleDevTools' as const }, { type: 'separator' as const }]),
        { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: `About ${PRODUCT_NAME}`,
          click: () => app.showAboutPanel()
        }
      ]
    }
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => event.preventDefault())
})

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
})

app.whenReady().then(async () => {
  app.setAboutPanelOptions({
    applicationName: PRODUCT_NAME,
    applicationVersion: app.getVersion(),
    copyright: 'Find the moments first. Let the user decide.'
  })
  installCsp()
  installMediaProtocol()
  buildMenu()

  secretStore = new SecretStore()
  await secretStore.init()
  engine = new EngineClient()

  deployListeners()
  registerIpc(engine, secretStore, () => mainWindow)
  createWindow()

  engine.on('event', (event) => send('engine:event', event))
  engine.on('status', (payload) => {
    mainLog(`engine status: ${payload.status}${payload.detail ? ` (${payload.detail})` : ''}`)
    send('engine:status', payload)
  })
  engine.on('fatal', (payload) => send('engine:fatal', payload))

  engine.start().catch((error) => {
    mainLog(`engine start failed: ${error?.message || String(error)}`)
    send('engine:status', { status: 'failed', detail: error?.message || String(error) })
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

function deployListeners() {
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
  app.on('before-quit', (event) => {
    if (quitting) return
    event.preventDefault()
    quitting = true
    engine
      ?.stop()
      .catch(() => undefined)
      .finally(() => app.exit(0))
  })
}

process.on('uncaughtException', (error) => {
  console.error('main process uncaught exception', error)
  mainLog(`uncaught exception: ${error?.stack || String(error)}`)
})

process.on('unhandledRejection', (reason) => {
  console.error('main process unhandled rejection', reason)
  mainLog(`unhandled rejection: ${String(reason)}`)
})
