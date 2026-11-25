import { _electron as electron } from '@playwright/test'
import { createServer } from 'node:http'
import { rmSync } from 'node:fs'

const APP = '/home/Binayak/.deepai-code/projects/clipwright/apps/desktop'
const FIXTURE = '/home/Binayak/.deepai-code/projects/clipwright/tests/fixtures/demo-lecture.mp4'
const SHOTS = '/home/Binayak/.deepai-code/projects/clipwright/docs/screenshots'
const USER_DATA = '/tmp/cw-ratelimit'
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const stub = createServer((req, res) => {
  res.writeHead(429, { 'content-type': 'application/json', 'retry-after': '30' })
  res.end(JSON.stringify({ error: { message: 'Rate limit reached for this demo stub.', type: 'rate_limit_exceeded' } }))
})
await new Promise((resolve) => stub.listen(8799, '127.0.0.1', resolve))
rmSync(USER_DATA, { recursive: true, force: true })

const app = await electron.launch({
  args: ['.', '--no-sandbox'],
  cwd: APP,
  env: { ...env, CLIPWRIGHT_USER_DATA: USER_DATA, CLIPWRIGHT_E2E: '1' }
})
try {
  const page = await app.firstWindow()
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.waitForTimeout(3500)
  const skip = page.getByRole('button', { name: 'Skip setup' })
  if (await skip.isVisible().catch(() => false)) await skip.click()
  await page.waitForTimeout(1200)
  const projectId = await page.evaluate(async (fixture) => {
    await window.clipwright.setSecret('stub-limit', 'test-key')
    await window.clipwright.request('provider.save', {
      profile: {
        id: 'stub-limit',
        name: 'Rate limit demo',
        adapter: 'openai_compatible',
        baseUrl: 'http://127.0.0.1:8799/v1',
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
    const project = await window.clipwright.request('project.create', { name: 'Rate limit, observed' })
    await window.clipwright.request('source.import_file', { projectId: project.project.id, path: fixture })
    return project.project.id
  }, FIXTURE)
  await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
  await page.reload()
  await page.waitForTimeout(3500)
  const transcribe = page.getByRole('button', { name: /Transcribe source/ })
  await transcribe.scrollIntoViewIfNeeded()
  await transcribe.click()
  await page.locator('.dot.wait').waitFor({ timeout: 30000 })
  await page.waitForTimeout(600)
  await page.screenshot({ path: `${SHOTS}/18-rate-limit-wait.png`, animations: 'disabled' })
  console.log('shot 18-rate-limit-wait.png')
  await page.getByRole('button', { name: 'Cancel' }).click().catch(() => {})
} finally {
  await app.close()
  stub.close()
  rmSync(USER_DATA, { recursive: true, force: true })
}
