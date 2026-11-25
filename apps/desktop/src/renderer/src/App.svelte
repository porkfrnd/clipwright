<script lang="ts">
  import { onMount } from 'svelte'
  import { appState, refreshBoot, parseRoute, setRoute, ingestJobEvent, toast } from '$lib/state.svelte'
  import { request } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import ToastStack from '$components/ToastStack.svelte'
  import Home from '$routes/Home.svelte'
  import Projects from '$routes/Projects.svelte'
  import ProjectView from '$routes/Project.svelte'
  import Studio from '$routes/Studio.svelte'
  import Settings from '$routes/Settings.svelte'
  import Models from '$routes/Models.svelte'
  import Wizard from '$routes/Wizard.svelte'
  import Recovery from '$routes/Recovery.svelte'

  const nav = [
    { id: 'home', label: 'Home', icon: 'home' },
    { id: 'projects', label: 'Projects', icon: 'projects' },
    { id: 'models', label: 'Model Manager', icon: 'models' },
    { id: 'settings', label: 'Settings', icon: 'settings' }
  ]

  let bootError = $state<string | null>(null)
  let booting = $state(true)
  let wizardOpen = $state(false)
  let shellReady = $state(false)
  let bootLog = $state<string[]>([])
  let bootAttempt: Promise<void> | null = null

  const routeMeta: Record<string, { title: string; eyebrow: string }> = {
    home: { title: 'The cutting room', eyebrow: 'Workspace' },
    projects: { title: 'Projects', eyebrow: 'Library' },
    project: { title: 'Find moments', eyebrow: 'Discovery' },
    studio: { title: 'Shorts Studio', eyebrow: 'Edit & export' },
    settings: { title: 'Settings', eyebrow: 'Preferences' },
    models: { title: 'Model Manager', eyebrow: 'Local assets' }
  }

  const currentProject = $derived(appState.projects.find((p: any) => p.id === appState.projectId))
  const defaultProfile = $derived(appState.providers.find((p: any) => p.id === (appState.defaultProfileId || appState.providers[0]?.id)))
  const engineReady = $derived(appState.engineStatus === 'ready')
  const bootStage = $derived(
    engineReady ? (appState.booted ? 3 : 2) : ['starting', 'restarting'].includes(appState.engineStatus) ? 1 : 0
  )
  const bootStatus = $derived(
    bootError
      ? 'Waiting for a clean start'
      : appState.engineStatus === 'failed'
        ? 'Media engine unavailable'
        : engineReady
          ? 'Preparing the workspace'
          : 'Starting the media engine'
  )

  onMount(() => {
    parseRoute()
    window.addEventListener('hashchange', parseRoute)
    const offEvent = window.clipwright.onEngineEvent((event) => ingestJobEvent(event))
    const offStatus = window.clipwright.onEngineStatus((payload) => {
      appState.engineStatus = payload.status
      appState.engineDetail = payload.detail || ''
      if (payload.status === 'ready') ensureBoot()
      if (payload.status === 'failed') refreshLogs()
    })
    const offFatal = window.clipwright.onEngineFatal((payload) => {
      appState.fatal = payload
    })
    window.clipwright
      .engineStatus()
      .then(async (status) => {
        appState.engineStatus = status.status
        if (status.logTail?.length) bootLog = status.logTail.slice(-20)
        if (status.status === 'ready') ensureBoot()
        if (status.status === 'failed') refreshLogs()
      })
      .catch(() => undefined)

    // Engine events can arrive while the renderer is reloading. Poll while the
    // boot screen is visible so a recovered engine always gets another attempt.
    const poll = window.setInterval(async () => {
      if (shellReady) return
      try {
        const status = await window.clipwright.engineStatus()
        appState.engineStatus = status.status
        if (status.logTail?.length) bootLog = status.logTail.slice(-20)
        if (status.status === 'ready') ensureBoot()
      } catch {
        // main process may still be starting
      }
    }, 2500)
    return () => {
      window.clearInterval(poll)
      window.removeEventListener('hashchange', parseRoute)
      offEvent()
      offStatus()
      offFatal()
    }
  })

  async function refreshLogs() {
    try {
      bootLog = (await window.clipwright.logTail()).slice(-20)
    } catch {
      bootLog = []
    }
  }

  function finishBoot() {
    bootError = null
    wizardOpen = !appState.settings?.wizard?.completed
    shellReady = true
    booting = false
    if (wizardOpen) appState.route = 'wizard'
  }

  async function ensureBoot() {
    if (shellReady) return
    // A previous attempt can set appState.booted before failing at the very end.
    // Never let that leave the boot screen permanently stuck.
    if (appState.booted && appState.settings) {
      finishBoot()
      return
    }
    if (bootAttempt) return bootAttempt
    bootAttempt = (async () => {
      try {
        await refreshBoot()
        finishBoot()
      } catch (error) {
        bootError = error instanceof Error ? error.message : String(error)
        booting = true
        if (!shellReady) window.setTimeout(() => ensureBoot(), 1800)
      }
    })().finally(() => {
      bootAttempt = null
    })
    return bootAttempt
  }

  async function restartEngine() {
    appState.fatal = null
    bootError = null
    bootLog = []
    appState.engineStatus = 'restarting'
    try {
      const result = await window.clipwright.restartEngine()
      appState.engineStatus = result.status
      if (result.logTail?.length) bootLog = result.logTail.slice(-20)
      await ensureBoot()
      if (!shellReady) await refreshLogs()
    } catch (error) {
      bootError = error instanceof Error ? error.message : String(error)
      await refreshLogs()
    }
  }

  $effect(() => {
    if (!booting && appState.settings && !appState.settings.wizard.completed) {
      wizardOpen = true
    }
  })

  async function finishWizard() {
    wizardOpen = false
    appState.settings = { ...(appState.settings as any), wizard: { completed: true } }
    await request('settings.set', { key: 'wizard', value: { completed: true } })
    await refreshBoot()
    setRoute('home')
  }

  async function createProject(name: string) {
    const result = await request<{ project: any }>('project.create', { name })
    appState.projects = [result.project, ...appState.projects]
    return result.project
  }

  function navigate(id: string) {
    setRoute(id)
  }

  async function reload() {
    location.reload()
  }
</script>

{#if appState.fatal}
  <Recovery fatal={appState.fatal} onReload={reload} onRestart={restartEngine} />
{:else if booting && !shellReady}
  <div class="boot-screen">
    <div class="sr-only" role="status" aria-live="polite">{bootStatus}.</div>
    <div class="boot-sheet">
      <div class="boot-leader" aria-hidden="true">
        <div class="leader-head"><span>Clipwright / media engine</span><span>Reel 01</span></div>
        <div class="leader-gate">
          <div class="leader-sprockets"></div>
          <div class="leader-frame">
            <div class="leader-grid"></div>
            <div class="leader-cross"></div>
            <div class="leader-count">C</div>
            <div class="leader-scan"></div>
            <span class="leader-corner tl"></span>
            <span class="leader-corner tr"></span>
            <span class="leader-corner bl"></span>
            <span class="leader-corner br"></span>
          </div>
          <div class="leader-sprockets"></div>
        </div>
        <div class="leader-ruler"><span>00:00</span><span>00:04</span><span>00:08</span><span>00:12</span></div>
        <div class="leader-foot"><span>9:16</span><span>1080 × 1920</span><span>30 FPS</span></div>
      </div>

      <div class="boot-copy">
        <div class="eyebrow">Preparing the cutting room</div>
        <h1>Setting the bench.</h1>
        <p class="boot-intro">
          A quiet workspace for finding the moments that travel. Clipwright is waking the media engine
          and reading your library.
        </p>
        <div class="boot-progress" aria-hidden="true">
          <span style={`width:${bootStage === 0 ? 12 : bootStage === 1 ? 38 : bootStage === 2 ? 70 : 92}%`}></span>
        </div>
        <div class="boot-steps" aria-label="Startup progress">
          <div class={`boot-step ${bootStage >= 1 ? 'done' : ''} ${bootStage === 0 ? 'active' : ''}`}>
            <span class="boot-step-index">01</span>
            <div>
              <div class="boot-step-name">Media engine</div>
              <div class="boot-step-note">FFmpeg, yt-dlp and the local AI runtime</div>
            </div>
            <span class="boot-step-state">{appState.engineStatus === 'failed' ? 'Offline' : engineReady ? 'Ready' : 'Starting'}</span>
          </div>
          <div class={`boot-step ${bootStage >= 2 ? 'done' : ''} ${bootStage === 1 ? 'active' : ''}`}>
            <span class="boot-step-index">02</span>
            <div>
              <div class="boot-step-name">Library</div>
              <div class="boot-step-note">Projects, transcripts and your last working state</div>
            </div>
            <span class="boot-step-state">{appState.booted ? 'Ready' : engineReady ? 'Loading' : 'Waiting'}</span>
          </div>
          <div class={`boot-step ${bootStage >= 3 ? 'done' : ''} ${bootStage === 2 ? 'active' : ''}`}>
            <span class="boot-step-index">03</span>
            <div>
              <div class="boot-step-name">Workspace</div>
              <div class="boot-step-note">Preferences, theme and the editing bench</div>
            </div>
            <span class="boot-step-state">{shellReady ? 'Ready' : appState.booted ? 'Finishing' : 'Waiting'}</span>
          </div>
        </div>

        {#if appState.engineStatus === 'failed'}
          <div class="boot-alert">
            <div>
              <strong>The media engine did not start.</strong>
              <span>{appState.engineDetail || 'The engine process stopped before it was ready.'}</span>
            </div>
            <div class="row tight">
              <button class="btn ghost sm" onclick={restartEngine}>Restart engine</button>
              <button class="btn ghost sm" onclick={reload}>Reload window</button>
            </div>
          </div>
        {/if}
        {#if bootError}
          <div class="boot-alert">
            <div>
              <strong>The workspace could not finish loading.</strong>
              <span>{bootError}</span>
            </div>
            <div class="row tight">
              <button class="btn ghost sm" onclick={ensureBoot}>Try again</button>
              {#if appState.engineStatus !== 'ready'}<button class="btn ghost sm" onclick={restartEngine}>Restart engine</button>{/if}
            </div>
          </div>
        {/if}
        {#if bootLog.length}
          <details class="boot-log">
            <summary>Technical log</summary>
            <pre>{bootLog.join('\n')}</pre>
          </details>
        {/if}
      </div>
    </div>
    <div class="boot-foot">
      <span>No account. No upload. Your files stay here.</span>
      <span>{booting ? 'Opening shortly' : 'Ready'}</span>
    </div>
  </div>
{:else if wizardOpen}
  <Wizard onFinish={finishWizard} onSkip={finishWizard} />
{:else}
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">C</div>
        <div>
          <div class="brand-name">Clipwright</div>
          <div class="brand-sub">Short-form editor</div>
        </div>
      </div>

      {#if currentProject}
        <button class="rail-project" onclick={() => setRoute('project', currentProject.id)} title="Open {currentProject.name}">
          <span class="rail-project-kicker">Open project</span>
          <span class="rail-project-name">{currentProject.name}</span>
          <span class="rail-project-meta">
            {currentProject.counts?.sources || 0} source{currentProject.counts?.sources === 1 ? '' : 's'}
            · {currentProject.counts?.selections || 0} selected
          </span>
        </button>
      {/if}

      <nav class="nav" aria-label="Main">
        <div class="nav-label">Workspace</div>
        {#each nav.slice(0, 2) as item}
          <button
            class={`nav-item ${appState.route === item.id ? 'active' : ''}`}
            onclick={() => navigate(item.id)}
          >
            <Icon name={item.icon} size={16} />
            <span>{item.label}</span>
          </button>
        {/each}

        {#if appState.projectId}
          <div class="nav-label">Project</div>
          <button class={`nav-item ${appState.route === 'project' ? 'active' : ''}`} onclick={() => setRoute('project', appState.projectId!)}>
            <Icon name="discovery" size={16} />
            <span>Discovery</span>
          </button>
          <button class={`nav-item ${appState.route === 'studio' ? 'active' : ''}`} onclick={() => setRoute('studio', appState.projectId!)}>
            <Icon name="studio" size={16} />
            <span>Studio</span>
          </button>
        {/if}

        <div class="nav-label">System</div>
        {#each nav.slice(2) as item}
          <button
            class={`nav-item ${appState.route === item.id ? 'active' : ''}`}
            onclick={() => navigate(item.id)}
          >
            <Icon name={item.icon} size={16} />
            <span>{item.label}</span>
          </button>
        {/each}
      </nav>

      <div class="sidebar-foot">
        <div class="engine-chip" title={appState.engineDetail || ''}>
          <span class={`dot ${appState.engineStatus === 'ready' ? '' : appState.engineStatus === 'restarting' ? 'warn' : 'err'}`}></span>
          <span>Engine {appState.engineStatus}</span>
        </div>
        <div class="rail-foot-meta">
          <span>v{appState.appInfo?.version || '—'}</span>
          <span>{appState.hardware ? `${appState.hardware.cores} cores` : 'Checking hardware'}</span>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="crumbs">
          <span>{routeMeta[appState.route]?.eyebrow || 'Clipwright'}</span>
          <Icon name="chevron" size={10} />
          <strong>{['project', 'studio'].includes(appState.route) ? currentProject?.name || routeMeta[appState.route]?.title : routeMeta[appState.route]?.title || 'Workspace'}</strong>
        </div>
        <div class="spacer"></div>
        {#if currentProject && ['project', 'studio'].includes(appState.route)}
          <span class="topbar-project">{currentProject.counts?.sources || 0} sources · {currentProject.counts?.selections || 0} selected</span>
        {/if}
        <div class="topbar-note" title="Transcript excerpts are sent only to the provider you choose.">
          <Icon name="shield" size={13} />
          <span>Private by design</span>
        </div>
        <button class="icon-btn" title="Settings" onclick={() => navigate('settings')}><Icon name="settings" size={16} /></button>
      </header>

      <main class="content">
        {#if appState.route === 'home'}
          <Home {createProject} />
        {:else if appState.route === 'projects'}
          <Projects />
        {:else if appState.route === 'project'}
          <ProjectView />
        {:else if appState.route === 'studio'}
          <Studio />
        {:else if appState.route === 'settings'}
          <Settings onRerunWizard={() => (wizardOpen = true)} />
        {:else if appState.route === 'models'}
          <Models />
        {:else}
          <Home {createProject} />
        {/if}
      </main>

      <footer class="statusbar" aria-label="Application status">
        <span class="status-item"><span class={`dot ${appState.engineStatus === 'ready' ? '' : appState.engineStatus === 'restarting' ? 'warn' : 'err'}`}></span> Engine {appState.engineStatus}</span>
        <span class="status-divider"></span>
        <span class="status-item">{appState.hardware ? `${appState.hardware.os} · ${appState.hardware.cores} cores` : 'Checking hardware'}</span>
        <span class="status-spacer"></span>
        <span class="status-item">{defaultProfile ? (defaultProfile.adapter === 'local' ? 'Local AI' : defaultProfile.name) : 'No AI provider'}</span>
        <span class="status-divider"></span>
        <span class="status-item">v{appState.appInfo?.version || '—'}</span>
      </footer>
    </div>
  </div>
{/if}

<ToastStack />
