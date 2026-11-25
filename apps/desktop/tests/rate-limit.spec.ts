import { _electron as electron, expect, test } from '@playwright/test'
import { createServer, type Server } from 'node:http'
import { rmSync } from 'node:fs'
import { join, resolve } from 'node:path'

const APP_DIR = resolve(__dirname, '..')
const FIXTURE = resolve(APP_DIR, '../../tests/fixtures/demo-lecture.mp4')
const USER_DATA = '/tmp/clipwright-rate-limit-e2e'

test('cloud transcription surfaces a provider rate limit as a checkpointed wait', async () => {
  const server: Server = createServer((req, res) => {
    req.resume()
    req.on('end', () => {
      res.writeHead(429, { 'Content-Type': 'application/json', 'Retry-After': '30' })
      res.end('{"error":{"message":"slow down for the test"}}')
    })
  })
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('stub did not bind')

  rmSync(USER_DATA, { recursive: true, force: true })
  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE
  Object.assign(env, { CLIPWRIGHT_USER_DATA: USER_DATA, CLIPWRIGHT_E2E: '1' })
  const app = await electron.launch({ args: ['.', '--no-sandbox'], cwd: APP_DIR, env })
  try {
    const page = await app.firstWindow()
    await page.waitForLoadState('domcontentloaded')
    await page.getByRole('button', { name: 'Skip setup' }).click({ timeout: 60_000 })

    const baseUrl = `http://127.0.0.1:${address.port}/v1`
    const projectId = await page.evaluate(async ({ baseUrl, fixture }) => {
      await window.clipwright.setSecret('stub-limit', 'test-key')
      await window.clipwright.request('provider.save', {
        profile: {
          id: 'stub-limit',
          name: 'Rate limit stub',
          adapter: 'openai_compatible',
          baseUrl,
          defaultModel: 'stub-model',
          enabled: true
        }
      })
      await window.clipwright.request('settings.set', { key: 'providers', value: { defaultProfileId: 'stub-limit' } })
      const now = new Date().toISOString()
      await window.clipwright.request('settings.set', {
        key: 'privacy',
        value: { authorizationAcknowledgedAt: now, providerDisclosureAt: now }
      })
      await window.clipwright.request('settings.set', {
        key: 'transcription',
        value: {
          engine: 'cloud_openai',
          cloudModel: 'whisper-large-v3-turbo',
          providerProfileId: 'stub-limit',
          preferCaptions: true,
          language: 'en'
        }
      })
      const project = await window.clipwright.request('project.create', { name: 'Rate limit test' })
      await window.clipwright.request('source.import_file', { projectId: project.project.id, path: fixture })
      return project.project.id as string
    }, { baseUrl, fixture: FIXTURE })

    await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
    await page.reload()
    await page.getByRole('button', { name: /Transcribe source/ }).click({ timeout: 60_000 })

    const banner = page.locator('.card.tight').filter({ hasText: /rate limiting/i })
    await expect(banner).toBeVisible({ timeout: 30_000 })
    await expect(banner.locator('.dot.wait')).toBeVisible()
    await expect(banner).toContainText(/resumes where it stopped/i)
    await expect(banner).toContainText(/\d+s/)
    await expect(page.getByText(/Choose a speech service provider/i)).toHaveCount(0)
    await banner.getByRole('button', { name: 'Cancel' }).click()
  } finally {
    await app.close()
    await new Promise<void>((done) => server.close(() => done()))
    rmSync(USER_DATA, { recursive: true, force: true })
  }
})
