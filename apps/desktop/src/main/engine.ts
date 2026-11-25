import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createWriteStream, existsSync, mkdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { EventEmitter } from 'node:events'
import { app } from 'electron'
import { PROTOCOL_VERSION, PRODUCT_NAME } from '../shared/brand'
import type { EngineEvent, EngineResponse, EngineStatus } from '../shared/types'

interface Pending {
  resolve: (value: any) => void
  reject: (error: EngineError) => void
  timer: NodeJS.Timeout
}

export class EngineError extends Error {
  code: string
  details?: Record<string, any>
  retryable?: boolean
  constructor(code: string, message: string, details?: Record<string, any>, retryable = false) {
    super(message)
    this.code = code
    this.details = details
    this.retryable = retryable
  }
}

export class EngineClient extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null
  private pending = new Map<string, Pending>()
  private buffer = ''
  private status: EngineStatus = 'stopped'
  private stopping = false
  private ready = false
  private pingTimer: NodeJS.Timeout | null = null
  private missedPings = 0
  private restarts: number[] = []
  private restartTimer: NodeJS.Timeout | null = null
  private logTail: string[] = []
  private logStream: ReturnType<typeof createWriteStream> | null = null
  readonly dataDir: string

  constructor() {
    super()
    this.dataDir = join(app.getPath('userData'), 'engine')
    mkdirSync(this.dataDir, { recursive: true })
    const logDir = app.getPath('logs')
    mkdirSync(logDir, { recursive: true })
    this.logStream = createWriteStream(join(logDir, 'engine-stderr.log'), { flags: 'a' })
  }

  getStatus(): EngineStatus {
    return this.status
  }

  getLogTail(): string[] {
    return [...this.logTail]
  }

  private setStatus(status: EngineStatus, detail?: string) {
    this.status = status
    this.emit('status', { status, detail })
  }

  private engineCommand(): { command: string; args: string[]; cwd: string } {
    const isDev = !app.isPackaged
    if (isDev) {
      const repoRoot = join(app.getAppPath(), '..', '..')
      const python =
        process.env.CLIPWRIGHT_PYTHON ||
        [join(repoRoot, '.venv', 'bin', 'python'), join(repoRoot, '.venv', 'Scripts', 'python.exe')].find(existsSync) ||
        (process.platform === 'win32' ? 'python' : 'python3')
      return { command: python, args: ['-m', 'shorts_engine', '--stdio'], cwd: repoRoot }
    }
    const exe = process.platform === 'win32' ? 'shorts-engine.exe' : 'shorts-engine'
    return {
      command: join(process.resourcesPath, 'engine', exe),
      args: ['--stdio'],
      cwd: join(process.resourcesPath, 'engine')
    }
  }

  async start(): Promise<void> {
    this.stopping = false
    this.spawnChild()
    await this.waitForReady(30000)
  }

  async restart(): Promise<void> {
    this.stopping = false
    this.ready = false
    this.restarts = []
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    this.stopPing()
    this.rejectAll(new EngineError('ENGINE_RESTARTING', 'The media engine is restarting.', {}, true))
    this.killChild()
    this.setStatus('restarting', 'Restarting the media engine')
    this.spawnChild()
    await this.waitForReady(30000)
  }

  private spawnChild() {
    if (this.child) this.killChild()
    const { command, args, cwd } = this.engineCommand()
    if (!existsSync(command) && command.includes('/')) {
      this.setStatus('failed', `Engine executable not found: ${command}`)
      throw new EngineError('ENGINE_MISSING', 'The media engine is missing from this build.')
    }
    this.setStatus('starting')
    this.ready = false
    this.buffer = ''
    this.missedPings = 0
    const child = spawn(command, args, {
      cwd,
      env: {
        ...process.env,
        CLIPWRIGHT_DATA_DIR: this.dataDir,
        CLIPWRIGHT_REPO_ROOT: !app.isPackaged ? join(app.getAppPath(), '..', '..') : process.resourcesPath,
        CLIPWRIGHT_RESOURCES: app.isPackaged
          ? join(process.resourcesPath, 'resources')
          : join(app.getAppPath(), '..', '..', 'resources'),
        PYTHONUNBUFFERED: '1'
      },
      detached: process.platform !== 'win32',
      stdio: ['pipe', 'pipe', 'pipe']
    })
    this.child = child
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => this.consume(chunk))
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk: string) => {
      for (const line of chunk.split(/\r?\n/)) {
        if (!line.trim()) continue
        this.logTail.push(line)
        if (this.logTail.length > 200) this.logTail.shift()
        this.logStream?.write(`${new Date().toISOString()} ${line}\n`)
      }
    })
    child.on('error', (error) => {
      this.setStatus('failed', error.message)
      this.rejectAll(new EngineError('ENGINE_SPAWN_FAILED', 'The media engine could not be started.'))
    })
    child.on('exit', (code, signal) => {
      // An old child can exit after restart()/spawnChild() has already replaced it.
      // Never reject the new child's requests or schedule another restart for a stale exit.
      const current = this.child === child
      if (current) this.child = null
      if (!current) return
      this.ready = false
      this.stopPing()
      this.rejectAll(new EngineError('ENGINE_STOPPED', 'The media engine stopped.', { code, signal }, true))
      if (this.stopping) {
        this.setStatus('stopped')
        return
      }
      this.scheduleRestart(`Engine exited (${code ?? signal ?? 'unknown'})`)
    })
    this.sendRaw('engine.hello', { protocolVersion: PROTOCOL_VERSION, appVersion: app.getVersion() }, 25000)
      .then((result) => {
        if (this.child !== child) return
        this.ready = true
        if (result.protocolVersion !== PROTOCOL_VERSION) {
          throw new EngineError('ENGINE_PROTOCOL_MISMATCH', 'The media engine has an incompatible protocol version.')
        }
        this.startPing()
        this.setStatus('ready')
      })
      .catch((error) => {
        if (this.child !== child) return
        this.rejectAll(error)
        if (!this.stopping) this.scheduleRestart(error.message)
      })
  }

  private waitForReady(timeoutMs: number): Promise<void> {
    if (this.status === 'ready') return Promise.resolve()
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.off('status', onStatus)
        reject(new EngineError('ENGINE_START_TIMEOUT', 'The media engine did not become ready.'))
      }, timeoutMs)
      const onStatus = ({ status }: { status: EngineStatus }) => {
        if (status === 'ready') {
          clearTimeout(timer)
          this.off('status', onStatus)
          resolve()
        } else if (status === 'failed') {
          clearTimeout(timer)
          this.off('status', onStatus)
          reject(new EngineError('ENGINE_FAILED', 'The media engine failed to start.'))
        }
      }
      this.on('status', onStatus)
    })
  }

  private consume(chunk: string) {
    this.buffer += chunk
    let index: number
    while ((index = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, index).trim()
      this.buffer = this.buffer.slice(index + 1)
      if (!line) continue
      let parsed: any
      try {
        parsed = JSON.parse(line)
      } catch {
        this.logTail.push(`[non-protocol stdout] ${line.slice(0, 400)}`)
        continue
      }
      if (parsed.kind === 'event') {
        this.emit('event', parsed as EngineEvent)
      } else if (parsed.kind === 'response') {
        const pending = this.pending.get(parsed.id)
        if (!pending) continue
        clearTimeout(pending.timer)
        this.pending.delete(parsed.id)
        const response = parsed as EngineResponse
        if (response.error) {
          pending.reject(
            new EngineError(
              response.error.code,
              response.error.message,
              response.error.details,
              response.error.retryable
            )
          )
        } else {
          pending.resolve(response.result ?? {})
        }
      }
    }
  }

  private sendRaw(method: string, params: Record<string, any>, timeoutMs = 120000, secrets?: Record<string, string>): Promise<any> {
    if (!this.child || !this.child.stdin.writable) {
      return Promise.reject(new EngineError('ENGINE_NOT_RUNNING', 'The media engine is not running.'))
    }
    const id = crypto.randomUUID()
    const payload = { v: PROTOCOL_VERSION, id, kind: 'request', method, params, ...(secrets ? { secrets } : {}) }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new EngineError('ENGINE_TIMEOUT', 'The media engine did not answer in time.', { method }, true))
      }, timeoutMs)
      this.pending.set(id, { resolve, reject, timer })
      this.child!.stdin.write(JSON.stringify(payload) + '\n')
    })
  }

  async request<T = any>(
    method: string,
    params: Record<string, any> = {},
    options: { timeoutMs?: number; secrets?: Record<string, string> } = {}
  ): Promise<T> {
    if (!this.ready && method !== 'engine.hello') {
      throw new EngineError('ENGINE_NOT_READY', 'The media engine is still starting.')
    }
    return this.sendRaw(method, params, options.timeoutMs ?? 120000, options.secrets)
  }

  private startPing() {
    this.stopPing()
    this.pingTimer = setInterval(async () => {
      if (!this.ready) return
      try {
        await this.sendRaw('engine.ping', {}, 6000)
        this.missedPings = 0
      } catch {
        this.missedPings += 1
        if (this.missedPings >= 3) {
          this.scheduleRestart('The media engine stopped responding')
        }
      }
    }, 8000)
  }

  private stopPing() {
    if (this.pingTimer) clearInterval(this.pingTimer)
    this.pingTimer = null
  }

  private scheduleRestart(reason: string) {
    if (this.stopping) return
    const now = Date.now()
    this.restarts = this.restarts.filter((t) => now - t < 60000)
    this.restarts.push(now)
    if (this.restarts.length > 3) {
      this.setStatus('failed', `${reason}. The engine restarted too many times.`)
      this.emit('fatal', { reason, logTail: this.getLogTail().slice(-40) })
      return
    }
    this.setStatus('restarting', reason)
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.restartTimer = setTimeout(() => {
      if (this.stopping) return
      try {
        this.spawnChild()
      } catch (error) {
        this.setStatus('failed', String(error))
      }
    }, 700)
  }

  private rejectAll(error: EngineError) {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer)
      pending.reject(error)
      this.pending.delete(id)
    }
  }

  private killChild() {
    const child = this.child
    if (!child) return
    this.child = null
    try {
      if (process.platform === 'win32' && child.pid) {
        spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'])
      } else if (child.pid) {
        process.kill(-child.pid, 'SIGKILL')
      }
    } catch {
      try {
        child.kill('SIGKILL')
      } catch {
        // already gone
      }
    }
  }

  async stop(): Promise<void> {
    this.stopping = true
    this.stopPing()
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.rejectAll(new EngineError('ENGINE_STOPPED', 'The app is closing.'))
    this.killChild()
    this.setStatus('stopped')
    this.logStream?.end()
  }
}
