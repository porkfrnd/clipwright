import { _electron as electron } from '@playwright/test'
import { createServer } from 'node:http'
import { join } from 'node:path'

const APP = '/home/Binayak/.deepai-code/projects/clipwright/apps/desktop'
const SHOTS = '/home/Binayak/.deepai-code/projects/clipwright/docs/screenshots'

const server = createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify({
    tag_name: 'v0.2.0',
    name: 'Clipwright 0.2.0',
    published_at: '2026-11-25T10:00:00Z',
    html_url: 'https://github.com/porkfrnd/clipwright/releases/tag/v0.2.0',
    body: '## A calmer cutting room\n\n- Discovery now batches adjacent windows more evenly.\n- The update check stays quiet unless something is actually new.\n- Fixed a focus trap in the compare sheet.\n\n### Under the hood\n\n`JobManager` keeps its checkpoint when a provider asks us to wait.',
    assets: [
      {
        name: 'Clipwright-0.2.0-x86_64.AppImage',
        size: 504000000,
        browser_download_url: 'https://github.com/porkfrnd/clipwright/releases/download/v0.2.0/Clipwright-0.2.0-x86_64.AppImage'
      },
      {
        name: 'Clipwright-0.2.0-amd64.deb',
        size: 409000000,
        browser_download_url: 'https://github.com/porkfrnd/clipwright/releases/download/v0.2.0/Clipwright-0.2.0-amd64.deb'
      }
    ]
  }))
})
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const port = server.address().port

const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
Object.assign(env, {
  CLIPWRIGHT_USER_DATA: '/tmp/cw-showcase',
  CLIPWRIGHT_E2E: '1',
  CLIPWRIGHT_UPDATE_API: `http://127.0.0.1:${port}/latest`
})

const app = await electron.launch({ args: ['.', '--no-sandbox'], cwd: APP, env })
const page = await app.firstWindow()
page.on('pageerror', (error) => console.log('PAGEERROR', error.message))
await page.waitForLoadState('domcontentloaded')
await page.waitForTimeout(4200)
await page.setViewportSize({ width: 1440, height: 900 })

// The showcase profile may have been left in another theme by screenshots.mjs.
await page.evaluate(async () => {
  const current = await window.clipwright.request('settings.get')
  const appSettings = { ...(current.settings?.app || {}), theme: 'velvet', appearance: 'dark', density: 'comfortable' }
  await window.clipwright.request('settings.set', { key: 'app', value: appSettings })
  location.reload()
})
await page.waitForTimeout(4200)
await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Updates' }).click()
await page.waitForTimeout(1600)
await page.screenshot({ path: join(SHOTS, '20-updates.png'), animations: 'disabled' })
console.log('shot 20-updates.png')
await app.close()
server.close()
