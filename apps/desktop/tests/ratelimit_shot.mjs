import { _electron as electron } from '@playwright/test'
import { createServer } from 'node:http'

const APP = '/home/Binayak/.deepai-code/projects/clipwright/apps/desktop'
const SHOTS = '/home/Binayak/.deepai-code/projects/clipwright/docs/screenshots'
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const stub = createServer((req, res) => {
  res.writeHead(429, { 'content-type': 'application/json', 'retry-after': '30' })
  res.end(JSON.stringify({ error: { message: 'Rate limit reached for this demo stub.', type: 'rate_limit_exceeded' } }))
})
await new Promise((resolve) => stub.listen(8799, '127.0.0.1', resolve))

const app = await electron.launch({
  args: ['.', '--no-sandbox'],
  cwd: APP,
  env: { ...env, CLIPWRIGHT_USER_DATA: '/tmp/cw-ratelimit' }
})
const page = await app.firstWindow()
await page.setViewportSize({ width: 1440, height: 900 })
await page.waitForTimeout(3500)
const projectId = await page.evaluate(async () => {
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
  const projects = await window.clipwright.request('project.list')
  return projects.projects.find((p) => p.counts.sources > 0).id
})
await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
await page.reload()
await page.waitForTimeout(3500)
const analyze = page.getByRole('button', { name: /Analyze the whole source/ })
await analyze.scrollIntoViewIfNeeded()
await analyze.click()
try {
  await page.locator('.dot.wait').waitFor({ timeout: 25000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${SHOTS}/18-rate-limit-wait.png`, animations: 'disabled' })
  console.log('shot 18-rate-limit-wait.png')
} catch (error) {
  console.log('rate-limit state not observed:', error.message.split('\n')[0])
  await page.screenshot({ path: `${SHOTS}/18-rate-limit-state.png`, animations: 'disabled' })
}
await page.getByRole('button', { name: 'Cancel' }).click().catch(() => {})
await app.close()
stub.close()
