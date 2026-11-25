<script lang="ts">
  import { appState, setRoute, refreshBoot, toast } from '$lib/state.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import { bytesLabel, durationLabel } from '$lib/categories'

  let { createProject }: { createProject: (name: string) => Promise<any> } = $props()

  let showNew = $state(false)
  let newName = $state('')
  let importing = $state(false)
  let dragOver = $state(false)
  let importingUrl = $state(false)
  let url = $state('')
  let urlError = $state<string | null>(null)
  let showUrl = $state(false)
  let authorized = $state(Boolean(appState.settings?.privacy.authorizationAcknowledgedAt))
  let recentProjects = $derived(appState.projects.slice(0, 4))

  const totals = $derived({
    projects: appState.projects.length,
    moments: appState.projects.reduce((sum: number, p: any) => sum + (p.counts?.selections || 0), 0),
    exports: appState.projects.reduce((sum: number, p: any) => sum + (p.counts?.exports || 0), 0)
  })

  async function newProject() {
    const name = newName.trim() || `Project ${appState.projects.length + 1}`
    try {
      const project = await createProject(name)
      showNew = false
      newName = ''
      setRoute('project', project.id)
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  async function ensureProject(): Promise<any> {
    if (appState.projects[0]) return appState.projects[0]
    const result = await request<{ project: any }>('project.create', { name: 'First project' })
    appState.projects = [result.project, ...appState.projects]
    return result.project
  }

  async function importLocal() {
    const chosen = await window.clipwright.openMediaDialog()
    if (!chosen) return
    await importPath(chosen.path)
  }

  async function dropFile(event: DragEvent) {
    event.preventDefault()
    dragOver = false
    const file = event.dataTransfer?.files?.[0]
    if (!file) return
    const path = await window.clipwright.registerDroppedFile(file)
    if (!path) {
      toast('error', 'That dropped item cannot be read as a local file.')
      return
    }
    await importPath(path)
  }

  async function importPath(path: string) {
    importing = true
    try {
      const project = await ensureProject()
      const result = await request('source.import_file', { projectId: project.id, path })
      toast('success', `Imported ${result.source.title}`)
      await refreshBoot()
      setRoute('project', project.id)
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      importing = false
    }
  }

  async function importUrl() {
    urlError = null
    importingUrl = true
    try {
      const project = await ensureProject()
      const acknowledged = appState.settings?.privacy.authorizationAcknowledgedAt
      if (!acknowledged || authorized) {
        await request('settings.set', {
          key: 'privacy',
          value: { authorizationAcknowledgedAt: new Date().toISOString() }
        })
        if (appState.settings) {
          appState.settings.privacy.authorizationAcknowledgedAt = new Date().toISOString()
        }
      }
      const result = await request('source.import_url', {
        projectId: project.id,
        url,
        authorizationAckAt: new Date().toISOString()
      })
      toast('success', `Imported ${result.source.title}`)
      await refreshBoot()
      setRoute('project', project.id)
    } catch (error: any) {
      urlError = errorText(error)
    } finally {
      importingUrl = false
    }
  }
</script>

<div class="page">
  <header class="page-head">
    <div>
      <div class="eyebrow">Workspace</div>
      <h1 style="margin-top:8px">Find the moment.<br /><span class="gold">Make it travel.</span></h1>
      <p>
        Import a long conversation, read the whole thing, and keep only the moments that stand on their own.
        Clipwright does the searching; you keep the taste.
      </p>
    </div>
    <div class="spacer"></div>
    <Button variant="primary" size="lg" onclick={() => (showNew = true)}><Icon name="plus" size={16} /> New project</Button>
  </header>

  <section class="overview-strip">
    <div class="overview-stats">
      <div class="stat">
        <div class="value">{String(totals.projects).padStart(2, '0')}</div>
        <div class="label">Projects</div>
      </div>
      <div class="overview-divider"></div>
      <div class="stat">
        <div class="value">{String(totals.moments).padStart(2, '0')}</div>
        <div class="label">Shorts selected</div>
      </div>
      <div class="overview-divider"></div>
      <div class="stat">
        <div class="value">{String(totals.exports).padStart(2, '0')}</div>
        <div class="label">Exports validated</div>
      </div>
    </div>
    <div class="overview-machine">
      <div class="eyebrow">This machine</div>
      <div class="small soft">
        {appState.hardware?.cpuModel || 'Checking CPU…'}
        {#if appState.hardware}· {appState.hardware.cores} cores · {bytesLabel(appState.hardware.ramBytes)}{/if}
      </div>
      <div class="row tiny muted">
        <span class="pill">{appState.hardware?.recommendedProfile || '—'} profile</span>
        {#if appState.hardware?.usableHardwareEncoder}<span class="pill success">{appState.hardware.usableHardwareEncoder}</span>{:else}<span class="pill">software encode</span>{/if}
      </div>
    </div>
  </section>

  <section class="workflow" aria-label="How Clipwright works">
    <div class="workflow-step">
      <span class="workflow-num">01</span>
      <div><strong>Bring the source</strong><span>A local file, or a link you are authorized to use.</span></div>
    </div>
    <div class="workflow-sep" aria-hidden="true"></div>
    <div class="workflow-step">
      <span class="workflow-num">02</span>
      <div><strong>Read the whole thing</strong><span>Captions or local Whisper turn speech into transcript.</span></div>
    </div>
    <div class="workflow-sep" aria-hidden="true"></div>
    <div class="workflow-step">
      <span class="workflow-num">03</span>
      <div><strong>Keep the moment</strong><span>Refine the cut in Studio, then export a vertical Short.</span></div>
    </div>
  </section>

  <div class="panel-grid">
    <section class="stack">
      <div class="section-title">
        <h2>Start something</h2>
        <div class="rule"></div>
      </div>
      <button
        class={`dropzone ${dragOver ? 'drag-over' : ''}`}
        onclick={importLocal}
        disabled={importing}
        ondragover={(e) => { e.preventDefault(); dragOver = true }}
        ondragleave={() => (dragOver = false)}
        ondrop={dropFile}
      >
        <Icon name="upload" size={44} />
        <div>
          <h3>{importing ? 'Reading the file…' : 'Drop in a local video'}</h3>
          <p class="small muted" style="margin-top:4px">MP4, MKV, WebM, MOV or audio. Nothing is uploaded.</p>
        </div>
        <span class="pill">Choose file</span>
      </button>

      <div class="card tight">
        <div class="spread">
          <div class="row">
            <Icon name="globe" size={18} />
            <div>
              <h3>Import from a link</h3>
              <p class="tiny muted">Uses yt-dlp. Only audio for the transcript and the sections you select are fetched.</p>
            </div>
          </div>
          <button class="link tiny" onclick={() => (showUrl = !showUrl)}>{showUrl ? 'Hide' : 'Open'}</button>
        </div>
        {#if showUrl}
          <div class="stack" style="margin-top:14px">
            <div class="notice warn">
              Only import content you own or are authorized to reuse. A reachable link is not permission to republish.
            </div>
            {#if !authorized}
              <label class="check">
                <input type="checkbox" bind:checked={authorized} />
                <span>I own this content or have permission to reuse it.</span>
              </label>
            {/if}
            <div class="row">
              <input class="input mono" bind:value={url} placeholder="https://…" aria-label="Video link" />
              <Button variant="primary" onclick={importUrl} disabled={importingUrl || !url.trim() || !authorized}>
                {importingUrl ? 'Checking…' : 'Import link'}
              </Button>
            </div>
            {#if urlError}
              <div class="notice error">
                {urlError}
                <button class="link" onclick={importLocal}>Import the file from disk instead</button>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </section>

    <section class="stack">
      <div class="section-title">
        <h2>Recent projects</h2>
        <div class="rule"></div>
      </div>
      {#if recentProjects.length}
        <div class="list">
          {#each recentProjects as project (project.id)}
            <button class="list-item" style="text-align:left" onclick={() => setRoute('project', project.id)}>
              <div style="width:38px;height:38px;border-radius:12px;background:var(--surface-3);display:grid;place-items:center">
                <Icon name="film" size={17} />
              </div>
              <div class="grow">
                <div class="small" style="font-weight:600">{project.name}</div>
                <div class="tiny muted">
                  {project.counts?.sources || 0} source{project.counts?.sources === 1 ? '' : 's'} ·
                  {project.counts?.selections || 0} selected
                </div>
              </div>
              <Icon name="chevron" size={14} />
            </button>
          {/each}
        </div>
      {:else}
        <div class="empty card">
          <svg class="line-art" viewBox="0 0 150 90" fill="none" stroke="currentColor" stroke-width="1.2">
            <rect x="14" y="20" width="122" height="50" rx="6" />
            <path d="M14 32h122M14 58h122M34 20v50M116 20v50" opacity=".5" />
            <circle cx="75" cy="45" r="10" />
            <path d="m72 40 8 5-8 5v-10Z" fill="currentColor" stroke="none" />
          </svg>
          <h3>No projects yet</h3>
          <p>Import a local file or a link, then Clipwright will read the whole conversation and propose moments.</p>
        </div>
      {/if}
    </section>
  </div>

  {#if showNew}
    <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (showNew = false)} role="presentation">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="new-title">
        <div>
          <div class="eyebrow">New project</div>
          <h2 id="new-title">Name the project</h2>
        </div>
        <div class="field">
          <label for="project-name">Project name</label>
          <input id="project-name" class="input" bind:value={newName} placeholder="Episode 14 · the quiet interview" onkeydown={(e) => e.key === 'Enter' && newProject()} autofocus />
        </div>
        <div class="row" style="justify-content:flex-end">
          <Button variant="ghost" onclick={() => (showNew = false)}>Cancel</Button>
          <Button variant="primary" onclick={newProject}>Create project</Button>
        </div>
      </div>
    </div>
  {/if}
</div>
