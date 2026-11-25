import { _electron as electron } from '@playwright/test'
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE
const app = await electron.launch({ args: ['.', '--no-sandbox'], cwd: '/home/Binayak/.deepai-code/projects/clipwright/apps/desktop', env: { ...env, CLIPWRIGHT_USER_DATA: '/tmp/cw-showcase', CLIPWRIGHT_E2E: '1' } })
const page = await app.firstWindow()
await page.waitForTimeout(120)
await page.screenshot({ path: '/tmp/edit-desk-boot.png', animations: 'disabled' })
await page.waitForTimeout(4000)
const projectId = await page.evaluate(async () => (await window.clipwright.request('project.list')).projects.find((p) => p.counts.sources > 0)?.id)
await page.evaluate((id) => { location.hash = `#/project/${id}` }, projectId)
await page.waitForTimeout(2400)
await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Studio' }).click()
await page.waitForTimeout(2800)
await page.screenshot({ path: '/tmp/edit-desk-studio.png', animations: 'disabled' })
await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: 'Model Manager' }).click()
await page.waitForTimeout(1800)
await page.screenshot({ path: '/tmp/edit-desk-models.png', animations: 'disabled' })
console.log('shots', projectId)
await app.close()
