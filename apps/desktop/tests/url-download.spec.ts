import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { createReadStream, existsSync, mkdirSync, rmSync, statSync } from 'node:fs'
import { createServer, type Server } from 'node:http'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'

const REPO = resolve(__dirname, '../../..')
const APP_DIR = resolve(__dirname, '..')
const VENV_PYTHON = join(REPO, '.venv/bin/python')
const FIXTURE = join(REPO, 'tests/fixtures/demo-lecture.mp4')
const USER_DATA = '/tmp/clipwright-url-e2e'
const OUTPUT_DIR = '/tmp/clipwright-url-e2e-output'

let app: ElectronApplication
let page: Page
let server: Server
let mediaUrl = ''

test.beforeAll(async () => {
  rmSync(USER_DATA, { recursive: true, force: true })
  rmSync(OUTPUT_DIR, { recursive: true, force: true })
  mkdirSync(OUTPUT_DIR, { recursive: true })
  execFileSync(VENV_PYTHON, [join(REPO, 'tests/e2e/prepare_ui.py'), join(USER_DATA, 'engine'), OUTPUT_DIR], { stdio: 'pipe' })

  // Serve the real fixture over HTTP. yt-dlp's generic extractor downloads it
  // exactly like a remote file, so this covers the URL import path without a
  // third-party site or a network dependency.
  server = createServer((req, res) => {
    if (!req.url?.startsWith('/lecture.mp4')) {
      res.writeHead(404).end('not found')
      return
    }
    const size = statSync(FIXTURE).size
    const range = req.headers.range
    if (range) {
      const match = /bytes=(\d+)-(\d*)/.exec(range)
      const start = match ? Number(match[1]) : 0
      const end = match && match[2] ? Number(match[2]) : size - 1
      res.writeHead(206, {
        'Content-Type': 'video/mp4',
        'Content-Length': end - start + 1,
        'Content-Range': `bytes ${start}-${end}/${size}`,
        'Accept-Ranges': 'bytes'
      })
      createReadStream(FIXTURE, { start, end }).pipe(res)
      return
    }
    res.writeHead(200, { 'Content-Type': 'video/mp4', 'Content-Length': size, 'Accept-Ranges': 'bytes' })
    createReadStream(FIXTURE).pipe(res)
  })
  await new Promise<void>((resolveListen) => server.listen(0, '127.0.0.1', () => resolveListen()))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('no server address')
  mediaUrl = `http://127.0.0.1:${address.port}/lecture.mp4`

  const env: Record<string, string> = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (key !== 'ELECTRON_RUN_AS_NODE' && value !== undefined) env[key] = value
  }
  Object.assign(env, {
    CLIPWRIGHT_USER_DATA: USER_DATA,
    CLIPWRIGHT_E2E: '1',
    CLIPWRIGHT_E2E_OUTPUT_DIR: OUTPUT_DIR
  })
  const executablePath = process.env.CLIPWRIGHT_E2E_EXECUTABLE
  app = executablePath
    ? await electron.launch({ executablePath, args: ['--no-sandbox'], cwd: APP_DIR, env })
    : await electron.launch({ args: ['.', '--no-sandbox'], cwd: APP_DIR, env })
  page = await app.firstWindow()
  page.on('pageerror', (error) => console.log('PAGEERROR', error.message))
  await page.waitForLoadState('domcontentloaded')
})

test.afterAll(async () => {
  await app?.close().catch(() => undefined)
  await new Promise<void>((resolveClose) => server?.close(() => resolveClose()))
})

test('URL import downloads through yt-dlp and transcribes', async () => {
  await expect(page.getByText('Setup · Step 1 of 5')).toBeVisible()
  await page.getByRole('button', { name: 'Skip setup' }).click()
  await expect(page.getByRole('button', { name: /Drop in a local video/ })).toBeVisible()

  await page.getByRole('button', { name: 'Import from link' }).evaluate((el) => (el as HTMLButtonElement).click())
  await expect(page.getByLabel('Video link')).toBeVisible()
  await expect(page.getByLabel(/I own this content or have permission/)).toBeVisible()
  await page.getByLabel(/I own this content or have permission/).evaluate((el) => (el as HTMLInputElement).click())
  await expect(page.getByLabel(/I own this content or have permission/)).toBeChecked()
  await page.getByLabel('Video link').fill(mediaUrl)
  await page.getByRole('button', { name: 'Import link' }).evaluate((el) => (el as HTMLButtonElement).click())
  await expect(page).toHaveURL(/#\/project\//, { timeout: 60_000 })
  await expect(page.getByText(/demo-lecture|lecture/i).first()).toBeVisible()

  await page.getByRole('button', { name: /Fetch transcript/ }).click()
  await expect(page.getByText(/transcript local whisper/i)).toBeVisible({ timeout: 180_000 })
})
