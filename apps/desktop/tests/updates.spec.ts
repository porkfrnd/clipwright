import { _electron as electron, expect, test } from '@playwright/test'
import { createServer, type Server } from 'node:http'
import { readFileSync, rmSync } from 'node:fs'
import { join, resolve } from 'node:path'

const APP_DIR = resolve(__dirname, '..')
const USER_DATA = '/tmp/clipwright-updates-e2e'
const VERSION = JSON.parse(readFileSync(join(APP_DIR, 'package.json'), 'utf8')).version as string

type Mode = 'available' | 'current' | 'error'

function release(tag: string) {
  return {
    tag_name: tag,
    name: `Clipwright ${tag.replace(/^v/, '')}`,
    published_at: '2026-11-25T10:00:00Z',
    html_url: `https://github.com/porkfrnd/clipwright/releases/tag/${tag}`,
    body: '## What changed\n\n- A calmer update path.\n- Release notes stay plain text.',
    assets: [
      {
        name: `Clipwright-${tag.replace(/^v/, '')}-x86_64.AppImage`,
        size: 1000000,
        browser_download_url: `https://github.com/porkfrnd/clipwright/releases/download/${tag}/Clipwright-${tag.replace(/^v/, '')}-x86_64.AppImage`
      }
    ]
  }
}

test('update checker: available, current, and failure states', async () => {
  const state = { mode: 'available' as Mode, requests: 0 }
  const server: Server = createServer((_req, res) => {
    state.requests += 1
    if (state.mode === 'error') {
      res.writeHead(500, { 'Content-Type': 'application/json' })
      res.end('{"message":"test outage"}')
      return
    }
    const tag = state.mode === 'current' ? `v${VERSION}` : 'v9.9.9'
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(release(tag)))
  })
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('stub did not bind')

  rmSync(USER_DATA, { recursive: true, force: true })
  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE
  Object.assign(env, {
    CLIPWRIGHT_USER_DATA: USER_DATA,
    CLIPWRIGHT_E2E: '1',
    CLIPWRIGHT_UPDATE_API: `http://127.0.0.1:${address.port}/latest`
  })

  const app = await electron.launch({ args: ['.', '--no-sandbox'], cwd: APP_DIR, env })
  try {
    const page = await app.firstWindow()
    await page.waitForLoadState('domcontentloaded')
    await page.getByRole('button', { name: 'Skip setup' }).click({ timeout: 60_000 })
    const nav = page.getByRole('navigation', { name: 'Main' })
    await expect(nav).toBeVisible()

    // The quiet banner and nav badge appear from the same cached state.
    await expect(page.locator('.update-strip')).toContainText('Clipwright 9.9.9 is available', { timeout: 30_000 })
    await expect(nav.getByRole('button', { name: /Updates/ })).toContainText('new')

    await nav.getByRole('button', { name: 'Updates' }).click()
    await expect(page.getByRole('heading', { name: 'Updates', exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'What changed', level: 2 })).toBeVisible()
    await expect(page.getByRole('button', { name: /Download for/ })).toBeVisible()
    await expect(page.locator('.update-strip')).toHaveCount(0)

    // Manual recheck must bypass the ten-minute cache.
    state.mode = 'current'
    await page.locator('.updates-head').getByRole('button', { name: 'Check again' }).click()
    await expect(page.getByText(/on the latest cut/i)).toBeVisible({ timeout: 15_000 })

    state.mode = 'error'
    await page.locator('.updates-head').getByRole('button', { name: 'Check again' }).click()
    await expect(page.getByText(/GitHub is unavailable right now/i)).toBeVisible({ timeout: 15_000 })
  } finally {
    await app.close()
    await new Promise<void>((done) => server.close(() => done()))
    rmSync(USER_DATA, { recursive: true, force: true })
  }
})
