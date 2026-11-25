import { _electron as electron } from '@playwright/test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const APP = '/home/Binayak/.deepai-code/projects/clipwright/apps/desktop'
const SHOTS = '/home/Binayak/.deepai-code/projects/clipwright/docs/screenshots'
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

async function launch(userData) {
  const app = await electron.launch({
    args: ['.', '--no-sandbox'],
    cwd: APP,
    env: { ...env, CLIPWRIGHT_USER_DATA: userData, CLIPWRIGHT_E2E: '1' }
  })
  const page = await app.firstWindow()
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message))
  await page.waitForTimeout(4000)
  return { app, page }
}

async function shot(page, name) {
  await page.screenshot({ path: join(SHOTS, name), animations: 'disabled' })
  console.log('shot', name)
}

async function openSettings(page) {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
  await page.waitForTimeout(700)
}

async function useTheme(page, theme, appearance = 'dark', density = 'comfortable') {
  await openSettings(page)
  await page.getByRole('button', { name: new RegExp('^' + theme, 'i') }).click()
  await page.getByRole('button', { name: appearance === 'light' ? 'Light' : 'Dark', exact: true }).click()
  await page.getByRole('button', { name: density === 'compact' ? 'Compact' : 'Comfortable', exact: true }).click()
  await page.waitForTimeout(900)
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Home' }).click()
  await page.waitForTimeout(1500)
}

const showcase = await launch('/tmp/cw-showcase')
let page = showcase.page
await page.setViewportSize({ width: 1440, height: 900 })
await shot(page, '01-home-velvet.png')

const projectId = await page.evaluate(async () => (await window.clipwright.request('project.list')).projects.find((p) => p.counts.sources > 0).id)
await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
await page.waitForTimeout(3000)
await shot(page, '02-discovery-velvet.png')

await page.getByRole('button', { name: 'Compare' }).click()
await page.waitForTimeout(1200)
await shot(page, '03-compare-velvet.png')
await page.getByRole('button', { name: 'Close compare' }).click()

await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Studio' }).click()
await page.waitForTimeout(2500)
await shot(page, '04-studio-velvet.png')

await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
await page.waitForTimeout(1800)
await shot(page, '05-settings-velvet.png')
await page.locator('text=Storage & privacy').scrollIntoViewIfNeeded()
await page.waitForTimeout(500)
await shot(page, '06-settings-privacy.png')
await page.locator('text=What gets sent').scrollIntoViewIfNeeded()
await page.waitForTimeout(500)
await shot(page, '06b-settings-privacy-lower.png')

await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Model Manager' }).click()
await page.waitForTimeout(1800)
await shot(page, '07-models.png')

await useTheme(page, 'ivory', 'light')
await shot(page, '08-home-ivory.png')
await useTheme(page, 'ember', 'dark')
await shot(page, '09-home-ember.png')
await useTheme(page, 'slate', 'dark')
await shot(page, '10-home-slate.png')
await useTheme(page, 'velvet', 'dark', 'compact')
await shot(page, '11-home-compact.png')

await page.setViewportSize({ width: 1120, height: 700 })
await page.waitForTimeout(800)
await shot(page, '12-home-small.png')
await page.setViewportSize({ width: 1600, height: 1000 })
await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
await page.waitForTimeout(2500)
await shot(page, '13-discovery-large.png')

// Empty project panel, using the same profile.
await page.evaluate(async () => {
  const p = await window.clipwright.request('project.create', { name: 'A room with nothing in it yet' })
  location.hash = `#/project/${p.project.id}`
})
await page.waitForTimeout(2200)
await shot(page, '14-empty-project.png')

// URL validation error on Home.
await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Home' }).click()
await page.waitForTimeout(800)
await page.getByRole('button', { name: 'Open' }).first().click()
await page.getByLabel('Video link').fill('not a link')
await page.getByRole('button', { name: 'Import link' }).click()
await page.waitForTimeout(1800)
await page.locator('.notice.error').scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {})
await page.waitForTimeout(300)
await shot(page, '15-url-error.png')

// A deliberately long project title, to check wrapping and header height.
await page.evaluate(async (id) => {
  await window.clipwright.request('project.rename', {
    projectId: id,
    name: 'The quiet interview about small moments, long silences, and the stories we keep telling ourselves'
  })
  location.hash = `#/project/${id}`
}, projectId)
await page.waitForTimeout(2200)
await shot(page, '19-long-title.png')

// First-launch wizard on a clean profile.
await page.evaluate(async () => {
  await window.clipwright.request('settings.set', { key: 'wizard', value: { completed: false } })
  location.hash = '#/home'
  location.reload()
})
await page.waitForTimeout(3500)
await shot(page, '16-wizard-welcome.png')
await page.evaluate(async () => {
  await window.clipwright.request('settings.set', { key: 'wizard', value: { completed: true } })
})
await showcase.app.close()

const fresh = mkdtempSync(join(tmpdir(), 'cw-empty-'))
const empty = await launch(fresh)
await empty.page.setViewportSize({ width: 1440, height: 900 })
await shot(empty.page, '17-first-launch-wizard.png')
await empty.app.close()
rmSync(fresh, { recursive: true, force: true })
