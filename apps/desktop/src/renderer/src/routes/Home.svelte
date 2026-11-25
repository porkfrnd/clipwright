<script lang="ts">
  import { appState, setRoute, refreshBoot, toast } from '$lib/state.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import { bytesLabel } from '$lib/categories'

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
  let lastProject = $derived(recentProjects[0] || null)

  function focusOnMount(node: HTMLInputElement) {
    requestAnimationFrame(() => node.focus())
  }

  const totals = $derived({
    projects: appState.projects.length,
    sources: appState.projects.reduce((sum: number, p: any) => sum + (p.counts?.sources || 0), 0),
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

<div class="page home-page">
  <section class="home-hero">
    <div class="hero-copy">
      <div class="eyebrow">Workspace / Home</div>
      <h1>Find the moment.<br /><span class="gold">Make it travel.</span></h1>
      <p class="hero-lede">
        Import a long conversation, read the whole thing, and keep only the moments that stand on their own.
        Clipwright finds the candidates; you keep the taste.
      </p>
      <div class="hero-actions">
        <Button variant="primary" size="lg" onclick={() => (showNew = true)}><Icon name="plus" size={17} /> New project</Button>
        <Button variant="ghost" size="lg" onclick={() => setRoute("projects")}><Icon name="folder" size={16} /> Open projects</Button>
      </div>
    </div>

    <aside class="bench" aria-label={lastProject ? "Last project on the bench" : "No project open"}>
      {#if lastProject}
        <button class="bench-card" onclick={() => setRoute("project", lastProject.id)}>
          <div class="bench-head"><span class="eyebrow">On the bench</span><Icon name="chevron" size={14} /></div>
          <div class="bench-body">
            <div class="bench-frame" aria-hidden="true">
              <span class="frame-index">9:16</span>
              <span class="frame-line"></span>
              <span class="frame-play"><Icon name="play" size={15} /></span>
              <span class="frame-caption">{lastProject.counts?.selections || 0} moment{(lastProject.counts?.selections || 0) === 1 ? "" : "s"} kept</span>
            </div>
            <div class="bench-meta">
              <h2>{lastProject.name}</h2>
              <p>{lastProject.counts?.sources || 0} source{lastProject.counts?.sources === 1 ? "" : "s"} · {lastProject.counts?.selections || 0} moments kept</p>
              <span class="bench-link">Resume discovery <Icon name="chevron" size={12} /></span>
            </div>
          </div>
        </button>
      {:else}
        <div class="bench-card empty">
          <div class="bench-head"><span class="eyebrow">On the bench</span><span class="tiny muted">Nothing yet</span></div>
          <div class="bench-body">
            <div class="bench-frame muted-frame" aria-hidden="true">
              <span class="frame-index">9:16</span>
              <span class="frame-line"></span>
              <span class="frame-play"><Icon name="film" size={16} /></span>
            </div>
            <div class="bench-meta">
              <h2>Your first source</h2>
              <p>A local file or a link you own. The transcript comes first.</p>
              <button class="link small" onclick={() => (showNew = true)}>Start a project</button>
            </div>
          </div>
        </div>
      {/if}
    </aside>
  </section>

  <section class="cut-rail" aria-label="Clipwright workflow">
    <div class="rail-start"><span class="rail-dot"></span><span>Import</span></div>
    <div class="rail-track"><span style="width:24%"></span><i>00:12</i></div>
    <div class="rail-step"><Icon name="text" size={12} /><span>Read</span></div>
    <div class="rail-track"><span style="width:50%"></span><i>00:34</i></div>
    <div class="rail-step"><Icon name="scissors" size={12} /><span>Cut</span></div>
    <div class="rail-track"><span style="width:76%"></span><i>00:58</i></div>
    <div class="rail-step"><Icon name="upload" size={12} /><span>Ship</span></div>
    <span class="rail-end">01:00</span>
  </section>

  <section class="kpi-band" aria-label="Workspace totals">
    <div class="kpi"><span class="kpi-icon gold"><Icon name="projects" size={17} /></span><div><strong>{totals.projects}</strong><span>Projects</span></div></div>
    <div class="kpi"><span class="kpi-icon blue"><Icon name="film" size={17} /></span><div><strong>{totals.sources}</strong><span>Sources</span></div></div>
    <div class="kpi"><span class="kpi-icon green"><Icon name="scissors" size={17} /></span><div><strong>{totals.moments}</strong><span>Clips selected</span></div></div>
    <div class="kpi"><span class="kpi-icon rose"><Icon name="upload" size={17} /></span><div><strong>{totals.exports}</strong><span>Exports validated</span></div></div>
    <div class="kpi-machine"><span class="dot"></span><div><strong>{appState.hardware?.recommendedProfile || "Checking"} profile</strong><span>{appState.hardware ? `${appState.hardware.cores} cores · ${bytesLabel(appState.hardware.ramBytes)}` : "Reading this machine"}</span></div></div>
  </section>

  <div class="home-grid">
    <section class="home-panel start-panel">
      <div class="panel-head"><div class="panel-title"><span class="panel-icon gold"><Icon name="spark" size={15} /></span><div><h2>Start something</h2><p>Drop a file, or bring a link you are allowed to use.</p></div></div></div>
      <button
        class={`dropzone dropzone-large ${dragOver ? "drag-over" : ""}`}
        onclick={importLocal}
        disabled={importing}
        ondragover={(e) => { e.preventDefault(); dragOver = true }}
        ondragleave={() => (dragOver = false)}
        ondrop={dropFile}
        aria-label="Drop in a local video or browse files"
      >
        <span class="drop-icon"><Icon name="upload" size={24} /></span>
        <span class="drop-title">{importing ? "Reading the file…" : "Drop a video here"}</span>
        <span class="drop-sub">or click to browse · MP4, MKV, WebM, MOV, audio up to 4 GB</span>
        <span class="drop-action"><Icon name="folder" size={13} /> Choose file</span>
      </button>
      <div class="import-row">
        <button class="import-pill" onclick={() => (showUrl = !showUrl)} aria-expanded={showUrl}>
          <Icon name="globe" size={15} /><span>Import from link</span><Icon name="chevron" size={12} />
        </button>
        <span class="tiny muted"><Icon name="shield" size={12} /> Only the sections you choose are downloaded.</span>
      </div>
      {#if showUrl}
        <div class="stack import-panel">
          <div class="notice warn">Only import content you own or are authorized to reuse. A reachable link is not permission to republish.</div>
          <label class="check"><input type="checkbox" bind:checked={authorized} /><span>I own this content or have permission to reuse it.</span></label>
          <div class="row">
            <input class="input mono" bind:value={url} placeholder="https://…" aria-label="Video link" />
            <Button variant="primary" onclick={importUrl} disabled={importingUrl || !url.trim() || !authorized}>{importingUrl ? "Checking…" : "Import link"}</Button>
          </div>
          {#if urlError}
            <div class="notice error">{urlError}<button class="link" onclick={importLocal}>Import the file from disk instead</button></div>
          {/if}
        </div>
      {/if}
    </section>

    <section class="home-panel recent-panel">
      <div class="panel-head"><div class="panel-title"><span class="panel-icon blue"><Icon name="clock" size={15} /></span><div><h2>Recent projects</h2><p>Pick up where the cutting room left off.</p></div></div><button class="link small" onclick={() => setRoute("projects")}>View all</button></div>
      {#if recentProjects.length}
        <div class="recent-list">
          {#each recentProjects as project (project.id)}
            <button class="recent-row" onclick={() => setRoute("project", project.id)}>
              <div class="recent-thumb"><Icon name="film" size={17} /><span>{String(project.counts?.selections || 0).padStart(2, "0")}</span></div>
              <div class="recent-copy"><strong>{project.name}</strong><span>{project.counts?.sources || 0} source{project.counts?.sources === 1 ? "" : "s"} · {project.counts?.selections || 0} selected</span></div>
              <Icon name="chevron" size={14} />
            </button>
          {/each}
        </div>
      {:else}
        <div class="recent-empty">
          <Icon name="film" size={22} />
          <div><strong>No projects yet</strong><p>Your first import will appear here with its sources and kept moments.</p></div>
          <button class="link small" onclick={() => (showNew = true)}>Create one</button>
        </div>
      {/if}
    </section>
  </div>

  <section class="feature-row" aria-label="How Clipwright works">
    <div class="feature"><span class="feature-icon gold"><Icon name="shield" size={16} /></span><div><strong>Local-first by default</strong><p>Your footage stays on this machine unless you pick a cloud provider.</p></div></div>
    <div class="feature"><span class="feature-icon blue"><Icon name="text" size={16} /></span><div><strong>Transcript-first discovery</strong><p>Every proposed clip points back to the words it came from.</p></div></div>
    <div class="feature"><span class="feature-icon green"><Icon name="frame" size={16} /></span><div><strong>Frame-checked exports</strong><p>Caption timing and vertical framing are verified after the render.</p></div></div>
  </section>
</div>

{#if showNew}
  <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (showNew = false)} role="presentation">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="new-title">
      <div><div class="eyebrow">New project</div><h2 id="new-title">Name the project</h2></div>
      <div class="field">
        <label for="project-name">Project name</label>
        <input id="project-name" class="input" bind:value={newName} placeholder="Episode 14 · the quiet interview" onkeydown={(e) => e.key === "Enter" && newProject()} use:focusOnMount />
      </div>
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (showNew = false)}>Cancel</Button>
        <Button variant="primary" onclick={newProject}>Create project</Button>
      </div>
    </div>
  </div>
{/if}
