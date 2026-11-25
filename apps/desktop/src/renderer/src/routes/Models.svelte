<script lang="ts">
  import { appState, refreshBoot, toast, trackJob } from '$lib/state.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import { bytesLabel } from '$lib/categories'

  let loading = $state(true)
  let listing = $state<any>({ items: [], diskUsageBytes: 0, modelsDir: '' })
  let binaries = $state<any>(null)
  let installing = $state<string | null>(null)
  let installProgress = $state<any>(null)
  let deleting = $state<any>(null)

  $effect(() => {
    load()
  })

  async function load() {
    loading = true
    try {
      const [models, bins] = await Promise.all([
        request('models.list').catch(() => null),
        request('binaries.status').catch(() => null)
      ])
      if (models) listing = models
      binaries = bins
    } finally {
      loading = false
    }
  }

  async function install(model: any) {
    installing = `${model.kind}:${model.name}`
    try {
      const job = await request('models.download', { kind: model.kind, name: model.name })
      trackJob({ ...job, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)
      while (true) {
        const { job: current } = await request('jobs.get', { jobId: job.jobId })
        installProgress = current
        if (['succeeded', 'failed', 'cancelled', 'interrupted'].includes(current.state)) {
          if (current.state === 'succeeded') {
            if (model.kind === 'llm') {
              const activated = await useLocal(model, false)
              toast(
                activated ? 'success' : 'info',
                activated
                  ? `${model.label} installed and selected for local analysis.`
                  : `${model.label} installed. Choose it with “Use for AI”.`
              )
            } else {
              toast('success', `${model.label} installed.`)
            }
          } else {
            toast('error', current.error?.message || 'Download did not finish.')
          }
          break
        }
        await new Promise((resolve) => setTimeout(resolve, 700))
      }
      await load()
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      installing = null
      installProgress = null
    }
  }

  async function verify(model: any) {
    try {
      const result = await request('models.verify', { modelId: model.id })
      if (result.ok) toast('success', `${model.label} passed verification.`)
      else toast('error', `${model.label} failed verification: ${result.reason || 'files changed'}`)
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  async function useLocal(model: any, notify = true): Promise<boolean> {
    const existing = appState.providers.find((p) => p.adapter === 'local')
    try {
      await request('provider.save', {
        profile: {
          ...(existing ? { id: existing.id } : {}),
          name: `${model.label} — local`,
          adapter: 'local',
          baseUrl: `local://${model.name}`,
          defaultModel: model.name,
          capabilities: {},
          default: true
        }
      })
      await refreshBoot()
      if (notify) toast('success', `${model.label} is now the default analysis model. No API key needed.`)
      return true
    } catch (error) {
      toast('error', errorText(error))
      return false
    }
  }

  async function remove() {
    if (!deleting) return
    try {
      await request('models.delete', { modelId: deleting.id })
      deleting = null
      await load()
      toast('success', 'Model removed.')
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  async function updateDownloader() {
    try {
      const result = await request('binaries.update', { channel: 'stable' })
      toast('success', `yt-dlp ${result.version} installed.`)
      await load()
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  const whisper = $derived(listing.items.filter((m: any) => m.kind === 'whisper'))
  const llm = $derived(listing.items.filter((m: any) => m.kind === 'llm'))
  const face = $derived(listing.items.filter((m: any) => m.kind === 'face'))
  const localProfile = $derived(appState.providers.find((p) => p.adapter === 'local'))
  const localIsDefault = $derived(Boolean(localProfile && localProfile.id === appState.defaultProfileId))
</script>

<div class="page">
  <header class="page-head">
    <div>
      <div class="eyebrow">Local assets</div>
      <h1 style="margin-top:6px">Model Manager</h1>
      <p>Whisper, local AI and face models download on demand into your data directory, never inside the install folder. Sizes are shown before anything starts.</p>
    </div>
    <div class="spacer"></div>
    <div class="row">
      <span class="pill">{bytesLabel(listing.diskUsageBytes)} installed</span>
      <Button variant="ghost" onclick={load}><Icon name="refresh" size={14} /> Refresh</Button>
    </div>
  </header>

  {#if installing && installProgress}
    <div class="card tight">
      <div class="spread">
        <span class="small">{installProgress.progress?.message || 'Downloading…'}</span>
        <span class="mono small">{Math.round((installProgress.progress?.fraction || 0) * 100)}%</span>
      </div>
      <div class="progress" style="margin-top:10px"><span style={`width:${Math.max(2, (installProgress.progress?.fraction || 0) * 100)}%`}></span></div>
    </div>
  {/if}

  <div class="panel-grid">
    <section class="stack">
      <div class="section-title"><h2>Whisper</h2><div class="rule"></div></div>
      <p class="small muted">
        Recommended for this machine: {listing.recommended?.join(', ') || '—'}. Model files are MIT-licensed OpenAI weights converted for faster-whisper.
      </p>
      <div class="list">
        {#each whisper as model (model.name)}
          <div class="list-item" style="align-items:flex-start">
            <div style="width:40px;height:40px;border-radius:12px;background:var(--surface-3);display:grid;place-items:center"><Icon name="mic" size={17} /></div>
            <div class="grow" style="display:grid;gap:3px">
              <div class="row"><strong class="small">{model.label}</strong>{#if model.installed}<span class="pill success">installed</span>{/if}</div>
              <div class="tiny muted">{model.languages} · download ≈ {model.downloadMb} MB · RAM ≈ {model.ramMb} MB · {model.tier}</div>
              <div class="tiny muted">{model.license}</div>
            </div>
            <div class="row tight">
              {#if model.installed}
                <Button size="sm" variant="ghost" onclick={() => verify(model)}>Verify</Button>
                <button class="icon-btn" title="Remove model" onclick={() => (deleting = model)} style="width:32px;height:32px"><Icon name="trash" size={13} /></button>
              {:else}
                <Button size="sm" variant="ghost" onclick={() => install(model)} disabled={Boolean(installing)}>
                  <Icon name="download" size={13} /> {installing === `whisper:${model.name}` ? 'Downloading…' : 'Install'}
                </Button>
              {/if}
            </div>
          </div>
        {/each}
      </div>

      <div class="section-title" style="margin-top:12px"><h2>Local AI</h2><div class="rule"></div></div>
      <p class="small muted">
        Find clips on this machine, with no API key and no transcript leaving your computer. Local analysis is slower and less nuanced than Groq; it is a privacy-first fallback, not a replacement for a larger model.
      </p>
      {#each llm as model (model.name)}
        <div class="list-item" style="align-items:flex-start">
          <div style="width:40px;height:40px;border-radius:12px;background:var(--surface-3);display:grid;place-items:center"><Icon name="spark" size={17} /></div>
          <div class="grow" style="display:grid;gap:3px">
            <div class="row">
              <strong class="small">{model.label}</strong>
              {#if model.installed}<span class="pill success">installed</span>{/if}
              {#if model.installed && localIsDefault}<span class="pill gold">default AI</span>{/if}
            </div>
            <div class="tiny muted">{model.languages} · download ≈ {model.downloadMb} MB · RAM ≈ {model.ramMb} MB · {model.tier}</div>
            <div class="tiny muted">{model.license} · runs locally through llama.cpp</div>
          </div>
          <div class="row tight">
            {#if model.installed}
              <Button size="sm" variant={localIsDefault ? 'ghost' : 'primary'} onclick={() => useLocal(model)} disabled={localIsDefault}>
                {localIsDefault ? 'Default AI' : 'Use for AI'}
              </Button>
              <Button size="sm" variant="ghost" onclick={() => verify(model)}>Verify</Button>
              <button class="icon-btn" title="Remove model" onclick={() => (deleting = model)} style="width:32px;height:32px"><Icon name="trash" size={13} /></button>
            {:else}
              <Button size="sm" variant="ghost" onclick={() => install(model)} disabled={Boolean(installing)}>
                <Icon name="download" size={13} /> {installing === `llm:${model.name}` ? 'Downloading…' : 'Install'}
              </Button>
            {/if}
          </div>
        </div>
      {/each}

      <div class="section-title" style="margin-top:12px"><h2>Face model</h2><div class="rule"></div></div>
      {#each face as model (model.name)}
        <div class="list-item">
          <div style="width:40px;height:40px;border-radius:12px;background:var(--surface-3);display:grid;place-items:center"><Icon name="target" size={17} /></div>
          <div class="grow">
            <div class="row"><strong class="small">{model.label}</strong>{#if model.installed}<span class="pill success">installed</span>{/if}</div>
            <div class="tiny muted">Used only if face tracking is enabled later. {model.license}</div>
          </div>
          {#if model.installed}
            <Button size="sm" variant="ghost" onclick={() => verify(model)}>Verify</Button>
          {:else}
            <Button size="sm" variant="ghost" onclick={() => install(model)} disabled={Boolean(installing)}>Install</Button>
          {/if}
        </div>
      {/each}
    </section>

    <aside class="stack">
      <section class="card tight">
        <div class="eyebrow">Downloader</div>
        <h3 style="margin-top:4px">yt-dlp</h3>
        {#if binaries}
          <div class="small mono muted" style="margin-top:8px">{binaries.ytdlp.version || 'not installed'}</div>
          <div class="tiny muted mono truncate" style="margin-top:4px" title={binaries.ytdlp.origin}>{(binaries.ytdlp.origin || '').split('/').filter(Boolean).slice(-3).join('/')}</div>
          {#if binaries.jsRuntime?.version}
            <div class="tiny muted truncate" style="margin-top:6px" title={`${binaries.jsRuntime.kind} ${binaries.jsRuntime.version}`}>
              JS runtime: {binaries.jsRuntime.version.split(' (')[0]}
            </div>
          {:else}
            <div class="notice warn" style="margin-top:10px">No JavaScript runtime. Some YouTube formats may be missing until Deno is bundled.</div>
          {/if}
          <Button size="sm" variant="ghost" onclick={updateDownloader} style="margin-top:12px"><Icon name="download" size={13} /> Update downloader</Button>
        {:else}
          <p class="small muted">Checking…</p>
        {/if}
      </section>
      <section class="card tight">
        <div class="eyebrow">Where models live</div>
        <div class="mono tiny muted" style="margin-top:6px">{listing.modelsDir}</div>
        <p class="tiny muted" style="margin-top:10px">
          Deleting a model frees its disk space; transcripts already made with it stay in your projects.
          Verification recomputes a hash over every file.
        </p>
      </section>
      <section class="card tight">
        <div class="eyebrow">Disk</div>
        <div class="numeric" style="font-size:40px;margin-top:4px">{bytesLabel(listing.diskUsageBytes)}</div>
        <div class="tiny muted">installed model files</div>
      </section>
    </aside>
  </div>
</div>

{#if deleting}
  <div class="drawer-backdrop" role="presentation">
    <div class="modal" role="alertdialog" aria-modal="true">
      <div class="eyebrow">Remove model</div>
      <h2>{deleting.label}</h2>
      <p class="soft">The model files will be deleted. Existing transcripts remain. You can install it again later; the download repeats.</p>
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (deleting = null)}>Keep it</Button>
        <Button variant="danger" onclick={remove}>Remove model</Button>
      </div>
    </div>
  </div>
{/if}
