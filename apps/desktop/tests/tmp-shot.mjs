import { _electron as electron } from '@playwright/test'
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ args: ['.', '--no-sandbox'], cwd: '/home/Binayak/.deepai-code/projects/clipwright/apps/desktop', env: { ...env, CLIPWRIGHT_USER_DATA: '/tmp/cw-showcase', CLIPWRIGHT_E2E: '1' } })
const page = await app.firstWindow()
page.on('pageerror', e => console.log('PAGEERROR', e.message))
await page.waitForTimeout(4500)
await page.screenshot({ path: '/tmp/edit-desk-home.png', animations: 'disabled' })
console.log('home shot')
const projectId = await page.evaluate(async () => (await window.clipwright.request('project.list')).projects.find((p) => p.counts.sources > 0)?.id)
if (projectId) {
  await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
  await page.waitForTimeout(2500)
  await page.screenshot({ path: '/tmp/edit-desk-project.png', animations: 'disabled' })
  console.log('project shot')
}
await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Settings' }).click()
await page.waitForTimeout(1200)
await page.screenshot({ path: '/tmp/edit-desk-settings.png', animations: 'disabled' })
console.log('settings shot')
await app.close()
