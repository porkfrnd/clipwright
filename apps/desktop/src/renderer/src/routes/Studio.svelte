<script lang="ts">
  import { tick } from 'svelte'
  import { appState, setRoute, toast, trackJob, jobState } from '$lib/state.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import Player from '$components/Player.svelte'
  import SubtitlePreview from '$components/SubtitlePreview.svelte'
  import SafeZoneOverlay from '$components/SafeZoneOverlay.svelte'
  import { timecode, durationLabel, bytesLabel, categoryMeta } from '$lib/categories'
  import type { Selection, EditSettings } from '$shared/types'

  let loading = $state(true)
  let error = $state<string | null>(null)
  let project = $state<any>(null)
  let sources = $state<any[]>([])
  let selections = $state<Selection[]>([])
  let activeId = $state<string | null>(null)
  let edit = $state<EditSettings | null>(null)
  let transcript = $state<any>(null)
  let presets = $state<any[]>([])
  let exportsQueue = $state<any[]>([])
  let player = $state<any>(null)
  let previewUrl = $state<string | null>(null)
  let previewStart = $state(0)
  let previewEnd = $state<number | null>(null)
  // Absolute source time represented by 0:00 in the current preview file.
  // URL previews are downloaded sections, while local files play in full.
  let previewOffset = $state(0)
  let previewFrameWidth = $state(0)
  let previewLoading = $state(false)
  let currentTime = $state(0)
  let activeJob = $state<any>(null)
  let renderError = $state<string | null>(null)
  let generating = $state(false)
  let outputDir = $state('')
  let quality = $state<'standard' | 'high'>('standard')
  let preferHardware = $state(true)
  let filenameTemplate = $state('{title}-{index}-{start}')
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let saving = $state(false)
  let musicPath = $state('')
  let syncBusy = $state(false)
  let syncError = $state<string | null>(null)
  let syncResult = $state<any>(null)
  let syncPreviewUrl = $state<string | null>(null)
  let syncPreviewBusy = $state(false)
  let syncPreviewOffset = $state(0)
  let tightenPlan = $state<any>(null)
  let tightenBusy = $state(false)
  let tightenError = $state<string | null>(null)
  let showSafeZones = $state(false)

  const active = $derived(selections.find((s) => s.id === activeId) || selections[0] || null)
  const activeSource = $derived(active ? sources.find((s) => s.id === active.candidate.sourceId) : null)
  const defaultProfile = $derived(appState.providers.find((p) => p.id === (appState.defaultProfileId || appState.providers[0]?.id)))
  const clipDuration = $derived(active ? active.candidate.endS - active.candidate.startS : 0)

  $effect(() => {
    if (appState.projectId) load()
  })

  $effect(() => {
    if (!active && selections.length) activeId = selections[0].id
  })

  $effect(() => {
    if (active) {
      edit = active.edit
      loadClip(active)
    }
  })

  $effect(() => {
    if (appState.settings) {
      outputDir = appState.settings.render.outputDir || ''
      quality = appState.settings.render.quality
      preferHardware = appState.settings.render.preferHardware
      filenameTemplate = appState.settings.render.filenameTemplate
    }
  })

  async function load() {
    loading = true
    error = null
    try {
      const opened = await request('project.open', { projectId: appState.projectId })
      project = opened.project
      sources = opened.sources || opened.project.sources || []
      selections = opened.selections || []
      presets = opened.presets || []
      exportsQueue = opened.exports || []
      if (selections.length && !activeId) activeId = selections[0].id
      await loadQueue()
    } catch (err) {
      error = errorText(err)
    } finally {
      loading = false
    }
  }

  async function loadQueue() {
    if (!appState.projectId) return
    const queue = await request('render.queue', { projectId: appState.projectId }).catch(() => null)
    if (queue) exportsQueue = queue.exports || []
  }

  async function loadClip(selection: Selection) {
    syncResult = null
    syncError = null
    syncPreviewUrl = null
    tightenPlan = null
    tightenError = null
    const source = sources.find((s) => s.id === selection.candidate.sourceId)
    const transcriptResult = await request('transcript.get', { sourceId: selection.candidate.sourceId }).catch(() => null)
    transcript = transcriptResult?.transcript || null
    if (!source) return
    previewOffset = 0
    if (source.kind === 'file' && source.mediaUrl) {
      previewUrl = source.mediaUrl
      previewStart = selection.candidate.startS
      previewEnd = selection.candidate.endS
    } else {
      previewLoading = true
      try {
        const result = await request('source.fetch_preview', {
          sourceId: source.id,
          startS: Math.max(0, selection.candidate.startS - 1),
          endS: selection.candidate.endS + 1
        })
        previewUrl = result.mediaUrl
        previewOffset = Number(result.startS ?? Math.max(0, selection.candidate.startS - 1))
        // The downloaded section includes padding before the chosen moment.
        // Start at the moment itself so subtitles are visible immediately.
        previewStart = Math.max(0, selection.candidate.startS - previewOffset)
        previewEnd = Math.max(previewStart + 0.2, selection.candidate.endS - previewOffset)
      } catch (err) {
        toast('error', errorText(err))
      } finally {
        previewLoading = false
      }
    }
    await tick()
    player?.seek(previewStart)
  }

  function selectClip(selection: Selection) {
    activeId = selection.id
  }

  function applyPreset(presetId: string) {
    if (!active) return
    const preset = presets.find((p) => p.id === presetId)
    if (!preset) return
    edit = { ...edit, ...preset.settings } as EditSettings
    scheduleSave()
    toast('success', `${preset.name} preset applied.`)
  }

  function update<K extends keyof EditSettings>(section: K, key: string, value: any) {
    if (!edit) return
    edit = { ...edit, [section]: { ...(edit[section] as any), [key]: value } }
    scheduleSave()
  }

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer)
    // Capture the selection and snapshot now. If the user switches clips before
    // the debounce fires, the edit must not be written to the new selection.
    const selectionId = active?.id
    const payload = edit
    saving = true
    saveTimer = setTimeout(async () => {
      saveTimer = null
      try {
        if (!selectionId || !payload) return
        const result = await request('edit.set', { selectionId, settings: payload })
        if (active?.id === selectionId) {
          edit = result.edit
          active.edit = result.edit
        }
      } catch (err) {
        toast('error', errorText(err))
      } finally {
        saving = false
      }
    }, 320)
  }

  function updateMetadata(key: string, value: any) {
    if (!edit) return
    edit = { ...edit, metadata: { ...edit.metadata, [key]: value } }
    scheduleSave()
  }

  async function generateMetadata() {
    if (!active) return
    generating = true
    try {
      const result = await request('metadata.generate', {
        candidateId: active.candidate.id,
        providerProfileId: defaultProfile?.id
      })
      const meta = result.metadata
      edit = {
        ...edit!,
        metadata: {
          title: meta.title || edit!.metadata.title,
          description: meta.description || edit!.metadata.description,
          hashtags: meta.hashtags || edit!.metadata.hashtags
        }
      }
      scheduleSave()
      toast('success', 'Metadata drafted. It is AI-generated; edit before publishing.')
    } catch (err) {
      toast('error', errorText(err))
    } finally {
      generating = false
    }
  }


  async function flushSave() {
    if (!active || !edit) return
    if (saveTimer) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
    const selectionId = active.id
    const payload = edit
    saving = true
    try {
      const result = await request('edit.set', { selectionId, settings: payload })
      if (active?.id === selectionId) {
        edit = result.edit
        active.edit = result.edit
      }
    } finally {
      saving = false
    }
  }

  function playheadS(): number {
    if (!active) return 0
    const absolute = currentTime + previewOffset
    return Math.max(active.candidate.startS, Math.min(absolute, active.candidate.endS - 2))
  }

  async function loadSyncPreview(startS: number, offsetMs: number) {
    if (!active) return
    syncPreviewBusy = true
    try {
      const result = await request('captions.preview', {
        selectionId: active.id,
        startS,
        durationS: 6,
        offsetMs
      })
      syncPreviewUrl = result.mediaUrl
      syncPreviewOffset = Number(result.offsetMs || offsetMs)
    } catch (err) {
      syncPreviewUrl = null
      toast('error', errorText(err))
    } finally {
      syncPreviewBusy = false
    }
  }

  async function checkSync() {
    if (!active || !edit) return
    syncBusy = true
    syncError = null
    syncResult = null
    syncPreviewUrl = null
    const selectionId = active.id
    const startS = playheadS()
    try {
      const result = await request('captions.sync_check', {
        selectionId,
        startS,
        durationS: 6
      })
      if (active?.id !== selectionId) return
      syncResult = result
      await loadSyncPreview(result.windowStartS, Number(edit.subtitles.offsetMs || 0))
    } catch (err) {
      if (active?.id === selectionId) syncError = errorText(err)
    } finally {
      syncBusy = false
    }
  }

  async function applySync() {
    if (!syncResult || !active) return
    update('subtitles', 'offsetMs', syncResult.offsetMs)
    try {
      await flushSave()
      await loadSyncPreview(syncResult.windowStartS, syncResult.offsetMs)
      toast('success', `Subtitle timing shifted by ${syncResult.offsetMs > 0 ? '+' : ''}${syncResult.offsetMs} ms.`)
    } catch (err) {
      toast('error', errorText(err))
    }
  }

  async function resetSync() {
    if (!active || !edit) return
    edit = {
      ...edit,
      subtitles: { ...edit.subtitles, offsetMs: 0, lineOffsetsMs: {} }
    }
    try {
      await flushSave()
      if (syncResult?.windowStartS != null) {
        await loadSyncPreview(syncResult.windowStartS, 0)
      }
      toast('success', 'Caption timing reset to source time.')
    } catch (err) {
      toast('error', errorText(err))
    }
  }

  async function nudgeSync(delta: number) {
    if (!edit || !active) return
    const next = Math.max(-1000, Math.min(1000, Number(edit.subtitles.offsetMs || 0) + delta))
    update('subtitles', 'offsetMs', next)
    try {
      await flushSave()
      if (syncResult?.windowStartS != null) await loadSyncPreview(syncResult.windowStartS, next)
    } catch (err) {
      toast('error', errorText(err))
    }
  }


  function setTighten(key: string, value: any) {
    if (!edit) return
    const current = edit.subtitles.tighten || { enabled: false, pauseThresholdS: 0.6, minPauseS: 0.25, removeFillers: false }
    edit = { ...edit, subtitles: { ...edit.subtitles, tighten: { ...current, [key]: value } } }
    tightenPlan = null
    scheduleSave()
  }

  async function reviewTighten() {
    if (!active || !edit) return
    tightenBusy = true
    tightenError = null
    const selectionId = active.id
    const config = edit.subtitles.tighten
    try {
      const plan = await request('timeline.plan', {
        selectionId,
        pauseThresholdS: config.pauseThresholdS,
        minPauseS: config.minPauseS,
        removeFillers: config.removeFillers
      })
      if (active?.id === selectionId) tightenPlan = plan
    } catch (err) {
      if (active?.id === selectionId) tightenError = errorText(err)
    } finally {
      tightenBusy = false
    }
  }

  async function applyTighten() {
    if (!tightenPlan?.supported) return
    setTighten('enabled', true)
    try {
      await flushSave()
      toast('success', `Tighten on: ${tightenPlan.removedS.toFixed(1)}s of dead air will be removed on export.`)
    } catch (err) {
      toast('error', errorText(err))
    }
  }

  async function chooseOutput() {
    const folder = await window.clipwright.chooseFolder()
    if (!folder) return
    outputDir = folder.path
    await request('settings.set', { key: 'render', value: { outputDir } }).catch(() => null)
    if (appState.settings) appState.settings.render.outputDir = outputDir
  }

  async function chooseMusic() {
    const file = await window.clipwright.openMediaDialog()
    if (file) {
      musicPath = file.path
      update('audio', 'musicPath', file.path)
    }
  }

  async function startRender(ids: string[]) {
    if (!ids.length) return
    renderError = null
    try {
      const job = await request('render.start', {
        projectId: appState.projectId,
        selectionIds: ids,
        outputDir,
        quality,
        preferHardware,
        filenameTemplate
      })
      trackJob({ ...job, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)
      const finished = await waitForJob(job.jobId)
      await loadQueue()
      if (finished.state === 'succeeded') {
        toast('success', 'Export finished and passed validation.')
      } else if (finished.state === 'interrupted') {
        renderError = finished.error?.message || 'The render stopped. You can resume it.'
      }
    } catch (err) {
      renderError = errorText(err)
    }
  }

  async function waitForJob(jobId: string) {
    activeJob = jobState.jobs[jobId] || { id: jobId, state: 'queued', progress: {} }
    while (true) {
      const { job } = await request('jobs.get', { jobId })
      activeJob = job
      trackJob(job)
      if (['succeeded', 'failed', 'cancelled', 'interrupted'].includes(job.state)) {
        if (job.error) renderError = job.error.message
        return job
      }
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
  }

  async function cancelRender() {
    if (!activeJob) return
    await request('jobs.cancel', { jobId: activeJob.id }).catch((err) => toast('error', errorText(err)))
    await loadQueue()
  }

  async function resumeRender() {
    if (!activeJob) return
    await request('jobs.resume', { jobId: activeJob.id })
    const job = await waitForJob(activeJob.id)
    await loadQueue()
    if (job.state === 'succeeded') toast('success', 'Export resumed and finished.')
  }

  async function showFile(path: string) {
    const ok = await window.clipwright.showItemInFolder(path)
    if (!ok) toast('error', 'That file is outside the chosen output folders.')
  }
</script>

{#if loading}
  <div class="page"><div class="empty card"><Icon name="loader" size={28} /><p>Opening the studio…</p></div></div>
{:else if error}
  <div class="page"><div class="notice error">{error}</div></div>
{:else if !selections.length}
  <div class="page">
    <header class="page-head">
      <div>
        <div class="eyebrow">Studio</div>
        <h1 style="margin-top:6px">Nothing on the bench</h1>
        <p>Choose at least one moment in Discovery, then bring it here to frame, caption and export.</p>
      </div>
      <div class="spacer"></div>
      <Button variant="primary" onclick={() => setRoute('project', appState.projectId!)}>Find moments</Button>
    </header>
    <div class="empty card"><Icon name="scissors" size={42} /><h3>No clips selected</h3><p>The Studio edits one selected moment at a time. Your selection tray lives in Discovery.</p></div>
  </div>
{:else if active && edit}
  <div class="page">
    <header class="page-head">
      <div style="min-width:0">
        <div class="row tight">
          <div class="eyebrow">Studio</div>
          <span class="pill" style={`--cat-color:${categoryMeta(active.candidate.category).color};color:${categoryMeta(active.candidate.category).color}`}>{categoryMeta(active.candidate.category).label}</span>
          {#if saving}<span class="pill">saving…</span>{/if}
          <span class={`pill ${Number(edit?.subtitles.offsetMs || 0) ? "success" : ""}`} title="Measured shift applied to every subtitle line">
            <Icon name="clock" size={11} />
            {#if Number(edit?.subtitles.offsetMs || 0)}
              timing {Number(edit.subtitles.offsetMs) > 0 ? "+" : ""}{edit.subtitles.offsetMs} ms
            {:else}
              timing at source
            {/if}
          </span>
        </div>
        <h1 style="margin-top:6px;max-width:840px">{active.candidate.title}</h1>
        <div class="row small muted" style="margin-top:8px">
          <span class="mono">{timecode(active.candidate.startS)} → {timecode(active.candidate.endS)}</span>
          <span>· {durationLabel(clipDuration)}</span>
          <span>· fit {Math.round(active.candidate.fitScore)}</span>
          {#if activeSource}<span>· {activeSource.title}</span>{/if}
        </div>
      </div>
      <div class="spacer"></div>
      <div class="row">
        <Button variant="ghost" onclick={() => setRoute('project', appState.projectId!)}><Icon name="discovery" size={14} /> Discovery</Button>
        <Button variant="primary" onclick={() => startRender([active.id])} disabled={activeJob && ['queued','running','waiting_rate_limit'].includes(activeJob.state)}>
          <Icon name="download" size={15} /> Export this clip
        </Button>
      </div>
    </header>

    {#if selections.length > 1}
      <div class="row" style="gap:8px;overflow-x:auto">
        {#each selections as selection (selection.id)}
          <button class={`pill ${selection.id === active.id ? 'gold' : ''}`} onclick={() => selectClip(selection)} style="max-width:240px">
            <span class="truncate">{selection.candidate.title}</span>
          </button>
        {/each}
      </div>
    {/if}

    <div class="studio-grid">
      <div class="stack">
        <div class="card tight">
          <div class="row" style="justify-content:space-between;margin-bottom:10px;gap:10px">
            <div class="eyebrow">Live preview</div>
            <div class="row" style="gap:6px">
              <label class="check tiny"><input type="checkbox" checked={showSafeZones} onchange={(e) => (showSafeZones = (e.currentTarget as HTMLInputElement).checked)} /><span>Safe zones</span></label>
              <select class="select compact" aria-label="Platform safe-zone preset" value={edit.subtitles.safeZone || "none"} onchange={(e) => update("subtitles", "safeZone", (e.currentTarget as HTMLSelectElement).value)}>
                <option value="none">No platform</option>
                <option value="tiktok">TikTok</option>
                <option value="reels">Reels</option>
                <option value="shorts">Shorts</option>
              </select>
            </div>
          </div>
          <div
            bind:clientWidth={previewFrameWidth}
            style="position:relative;width:min(430px, 34.875vh);margin:0 auto"
          >
            {#if previewLoading}
              <div class="player-frame"><div class="player-empty"><Icon name="loader" size={26} /><div style="margin-top:10px">Fetching just this section…</div></div></div>
            {:else}
              <Player
                bind:this={player}
                src={previewUrl}
                startS={previewStart}
                endS={previewEnd}
                layout={edit.framing.layout}
                zoom={edit.framing.zoom}
                onTime={(t) => (currentTime = t)}
              />
              <SubtitlePreview
                segments={transcript?.segments || []}
                startS={active.candidate.startS}
                endS={active.candidate.endS}
                current={currentTime + previewOffset}
                style={edit.subtitles}
                scale={previewFrameWidth ? previewFrameWidth / 1080 : 0.398}
              />
              <SafeZoneOverlay platform={edit.subtitles.safeZone || "none"} visible={showSafeZones} />
            {/if}
          </div>
        </div>

        <div class="card tight">
          <div class="spread" style="margin-bottom:10px">
            <h3>Publishing metadata</h3>
            <Button size="sm" variant="ghost" onclick={generateMetadata} disabled={generating}>
              {#if generating}<Icon name="loader" size={13} /> Drafting…{:else}<Icon name="spark" size={13} /> Draft with AI{/if}
            </Button>
          </div>
          <div class="stack">
            <div class="field">
              <label for="meta-title">Title</label>
              <input id="meta-title" class="input" value={edit.metadata.title || active.candidate.title} oninput={(e) => updateMetadata('title', (e.currentTarget as HTMLInputElement).value)} />
            </div>
            <div class="field">
              <label for="meta-description">Description</label>
              <textarea id="meta-description" class="textarea" value={edit.metadata.description} oninput={(e) => updateMetadata('description', (e.currentTarget as HTMLTextAreaElement).value)}></textarea>
            </div>
            <div class="field">
              <label for="meta-tags">Hashtags</label>
              <input id="meta-tags" class="input" value={(edit.metadata.hashtags || []).join(' ')} oninput={(e) => updateMetadata('hashtags', (e.currentTarget as HTMLInputElement).value.split(/\s+/).filter(Boolean))} />
            </div>
            <div class="notice">AI-generated text is a draft. It is never burned into the video or presented as the speaker's words.</div>
          </div>
        </div>

        <div class="card tight">
          <div class="spread" style="margin-bottom:10px">
            <h3>Export</h3>
            <span class="pill">1080 × 1920 · H.264</span>
          </div>
          <div class="form-grid">
            <div class="field wide">
              <label for="studio-output">Output folder</label>
              <div class="row">
                <input id="studio-output" class="input mono" readonly value={outputDir} />
                <Button variant="ghost" size="sm" onclick={chooseOutput}><Icon name="folder" size={13} /> Choose</Button>
              </div>
            </div>
            <div class="field">
              <label for="quality">Quality</label>
              <select id="quality" class="select" value={quality} onchange={(e) => { quality = (e.currentTarget as HTMLSelectElement).value as any; request('settings.set', { key: 'render', value: { quality } }) }}>
                <option value="standard">Standard · fast</option>
                <option value="high">High · slower</option>
              </select>
            </div>
            <div class="field">
              <label for="naming">File name</label>
              <input id="naming" class="input mono" value={filenameTemplate} oninput={(e) => { filenameTemplate = (e.currentTarget as HTMLInputElement).value; request('settings.set', { key: 'render', value: { filenameTemplate } }) }} />
            </div>
            <label class="check wide">
              <input type="checkbox" checked={preferHardware} onchange={(e) => { preferHardware = (e.currentTarget as HTMLInputElement).checked; request('settings.set', { key: 'render', value: { preferHardware } }) }} />
              <span>Use a hardware encoder when a test encode succeeds; otherwise fall back to libx264.</span>
            </label>
          </div>
          <div class="row" style="margin-top:14px">
            <Button variant="primary" onclick={() => startRender(selections.map((s) => s.id))} disabled={activeJob && ['queued','running','waiting_rate_limit'].includes(activeJob.state)}>
              <Icon name="download" size={15} /> Export all {selections.length}
            </Button>
            <span class="tiny muted">A clip is only marked successful after ffprobe validates resolution, codec, duration and audio.</span>
          </div>
        </div>
      </div>

      <div class="studio-controls">
        <div class="control-group">
          <div class="spread" style="margin-bottom:10px">
            <h3><Icon name="spark" size={16} /> Preset</h3>
            <select class="select" style="width:190px" onchange={(e) => applyPreset((e.currentTarget as HTMLSelectElement).value)}>
              <option value="">Apply preset…</option>
              {#each presets as preset}<option value={preset.id}>{preset.name}</option>{/each}
            </select>
          </div>
          <div class="seg">
            {#each [{ id: 'fill', label: 'Fill 9:16' }, { id: 'blur', label: 'Blur fit' }, { id: 'manual', label: 'Manual' }] as layout}
              <button class={edit.framing.layout === layout.id ? 'active' : ''} onclick={() => update('framing', 'layout', layout.id)}>{layout.label}</button>
            {/each}
          </div>
          <div class="field" style="margin-top:12px">
            <label for="zoom">Static zoom · {edit.framing.zoom.toFixed(2)}×</label>
            <input id="zoom" class="range" type="range" min="1" max="1.6" step="0.02" value={edit.framing.zoom} oninput={(e) => update('framing', 'zoom', Number((e.currentTarget as HTMLInputElement).value))} />
          </div>
          <p class="tiny muted">Face tracking is not enabled in this build. The crop stays centered so the frame remains calm.</p>
        </div>

        <div class="control-group">
          <div class="spread">
            <h3><Icon name="text" size={16} /> Subtitles</h3>
            <label class="check"><input type="checkbox" checked={edit.subtitles.enabled} onchange={(e) => update('subtitles', 'enabled', (e.currentTarget as HTMLInputElement).checked)} /><span>On</span></label>
          </div>
          <div class="form-grid" style="margin-top:12px">
            <div class="field">
              <label for="font-size">Size · {edit.subtitles.fontSize}px</label>
              <input id="font-size" class="range" type="range" min="42" max="92" step="2" value={edit.subtitles.fontSize} oninput={(e) => update('subtitles', 'fontSize', Number((e.currentTarget as HTMLInputElement).value))} />
            </div>
            <div class="field">
              <label for="position">Position</label>
              <select id="position" class="select" value={edit.subtitles.position} onchange={(e) => update('subtitles', 'position', (e.currentTarget as HTMLSelectElement).value)}>
                <option value="lower_third">Lower third (safe)</option>
                <option value="bottom">Bottom</option>
                <option value="center">Center</option>
              </select>
            </div>
            <div class="field">
              <span class="label">Text colour</span>
              <div class="swatch-row">
                {#each ['#FFFFFF', '#F7E8C3', '#7FD1C1', '#FFD4DA', '#C9A7FF'] as color}
                  <button class={`swatch ${edit.subtitles.color === color ? 'active' : ''}`} style={`background:${color}`} title={color} onclick={() => update('subtitles', 'color', color)}></button>
                {/each}
              </div>
            </div>
            <div class="field">
              <span class="label">Highlight colour</span>
              <div class="swatch-row">
                {#each ['#E8C77B', '#FF9A6F', '#7FD1C1', '#C9A7FF', '#FFFFFF'] as color}
                  <button class={`swatch ${edit.subtitles.highlightColor === color ? 'active' : ''}`} style={`background:${color}`} title={color} onclick={() => update('subtitles', 'highlightColor', color)}></button>
                {/each}
              </div>
            </div>
            <div class="field">
              <label for="outline">Outline · {edit.subtitles.outline}</label>
              <input id="outline" class="range" type="range" min="0" max="8" step="1" value={edit.subtitles.outline} oninput={(e) => update('subtitles', 'outline', Number((e.currentTarget as HTMLInputElement).value))} />
            </div>
            <div class="field">
              <label for="max-lines">Max lines</label>
              <select id="max-lines" class="select" value={edit.subtitles.maxLines} onchange={(e) => update('subtitles', 'maxLines', Number((e.currentTarget as HTMLSelectElement).value))}>
                <option value={1}>1 line</option>
                <option value={2}>2 lines</option>
              </select>
            </div>
            <label class="check wide"><input type="checkbox" checked={edit.subtitles.uppercase} onchange={(e) => update('subtitles', 'uppercase', (e.currentTarget as HTMLInputElement).checked)} /><span>Uppercase</span></label>
            <label class="check wide"><input type="checkbox" checked={edit.subtitles.background} onchange={(e) => update('subtitles', 'background', (e.currentTarget as HTMLInputElement).checked)} /><span>Background box</span></label>
          </div>
          {#if transcript?.wordTiming === 'approximate'}
            <div class="notice warn" style="margin-top:10px">Word timing is approximate, so the Studio highlights whole phrases instead of pretending to know each word's exact frame.</div>
          {/if}
          {#if edit.subtitles.safeZone !== "none" && edit.subtitles.position !== "center"}
            <div class="notice warn" style="margin-top:10px">
              The lower caption band can sit under {edit.subtitles.safeZone === "shorts" ? "Shorts" : edit.subtitles.safeZone === "reels" ? "Reels" : "TikTok"} controls. Center captions stay inside the reserved frame.
              <div class="row" style="margin-top:6px"><button class="link tiny" onclick={() => update("subtitles", "position", "center")}>Move captions to center</button></div>
            </div>
          {/if}
          <div class="timing-panel">
            <div class="spread">
              <div>
                <div class="eyebrow">Timing</div>
                <h4>Caption sync assistant</h4>
              </div>
              <Button size="sm" variant="ghost" onclick={checkSync} disabled={syncBusy}>
                {#if syncBusy}<Icon name="loader" size={13} /> Listening…{:else}<Icon name="clock" size={13} /> Check sync{/if}
              </Button>
            </div>
            <p class="tiny muted">
              Compares word onsets with local audio energy at the playhead. Runs on this device — nothing is uploaded.
            </p>
            {#if syncError}
              <div class="notice error tiny">{syncError}</div>
            {/if}
            {#if syncBusy}
              <div class="timing-skeleton" aria-hidden="true"><span></span><span></span></div>
            {:else if syncResult}
              <div class="timing-result">
                <div class="timing-number">
                  <strong>{syncResult.offsetMs > 0 ? "+" : ""}{syncResult.offsetMs}<span>ms</span></strong>
                  <div>
                    <span class={`pill ${syncResult.confidence === "High" ? "success" : "warn"}`}>{syncResult.confidence}</span>
                    <div class="tiny muted">{syncResult.wordsUsed} words · {syncResult.checkedS}s window</div>
                  </div>
                </div>
                <p class="tiny muted" style="margin:0">{syncResult.method}</p>
                <div class="row" style="margin-top:10px">
                  <Button size="sm" variant="primary" onclick={applySync} disabled={syncResult.offsetMs === 0 || syncResult.confidence !== "High"}>Apply shift</Button>
                  <Button size="sm" variant="ghost" onclick={() => nudgeSync(-40)}>−40 ms</Button>
                  <Button size="sm" variant="ghost" onclick={() => nudgeSync(40)}>+40 ms</Button>
                  <button class="link tiny" onclick={resetSync}>Reset</button>
                </div>
              </div>
              {#if syncPreviewBusy}
                <div class="sync-preview loading"><Icon name="loader" size={20} /><span>Rendering a 6-second check…</span></div>
              {:else if syncPreviewUrl}
                <div class="sync-preview">
                  <video src={syncPreviewUrl} controls playsinline preload="metadata">
                    <track kind="captions" label="Burned-in subtitle preview" srclang="en" />
                  </video>
                  <div class="spread tiny muted">
                    <span>Burned-in check · {syncPreviewOffset > 0 ? "+" : ""}{syncPreviewOffset} ms</span>
                    <span>local render</span>
                  </div>
                </div>
              {/if}
            {/if}
          </div>
        </div>

        <div class="control-group">
          <h3><Icon name="film" size={16} /> Effects</h3>
          <div class="stack">
            <label class="check"><input type="checkbox" checked={edit.effects.fade} onchange={(e) => update('effects', 'fade', (e.currentTarget as HTMLInputElement).checked)} /><span>Short fade in and out</span></label>
            <label class="check"><input type="checkbox" checked={edit.effects.progressBar} onchange={(e) => update('effects', 'progressBar', (e.currentTarget as HTMLInputElement).checked)} /><span>Progress bar</span></label>
            <label class="check"><input type="checkbox" checked={edit.effects.cinematic} onchange={(e) => update('effects', 'cinematic', (e.currentTarget as HTMLInputElement).checked)} /><span>Mild cinematic contrast and vignette</span></label>
            <p class="tiny muted">Defaults are restrained. The Minimal preset turns all of this off.</p>
          </div>
          <div class="tighten-panel">
            <div class="spread">
              <div>
                <h4>Pause & filler tightener</h4>
                <p class="tiny muted">Removes dead air and opted-in filler words from the export. Source and transcript stay untouched.</p>
              </div>
              <label class="check"><input type="checkbox" checked={!!edit.subtitles.tighten?.enabled} onchange={(e) => setTighten("enabled", (e.currentTarget as HTMLInputElement).checked)} /><span>On</span></label>
            </div>
            <div class="form-grid" style="margin-top:10px">
              <div class="field">
                <label for="pause-threshold">Cut pauses longer than {Number(edit.subtitles.tighten?.pauseThresholdS || 0.6).toFixed(1)}s</label>
                <input id="pause-threshold" class="range" type="range" min="0.4" max="2" step="0.1" value={edit.subtitles.tighten?.pauseThresholdS || 0.6} oninput={(e) => setTighten("pauseThresholdS", Number((e.currentTarget as HTMLInputElement).value))} />
              </div>
              <label class="check wide"><input type="checkbox" checked={!!edit.subtitles.tighten?.removeFillers} onchange={(e) => setTighten("removeFillers", (e.currentTarget as HTMLInputElement).checked)} /><span>Also remove detected fillers (um, uh, erm)</span></label>
            </div>
            <div class="row" style="margin-top:10px">
              <Button size="sm" variant="ghost" onclick={reviewTighten} disabled={tightenBusy}>
                {#if tightenBusy}<Icon name="loader" size={13} /> Reviewing…{:else}<Icon name="scissors" size={13} /> Review cuts{/if}
              </Button>
              {#if tightenPlan?.supported}
                <span class="pill success">{tightenPlan.removedS.toFixed(1)}s shorter · {tightenPlan.pauses.length} pause{tightenPlan.pauses.length === 1 ? "" : "s"}{tightenPlan.fillers.length ? ` · ${tightenPlan.fillers.length} filler${tightenPlan.fillers.length === 1 ? "" : "s"}` : ""}</span>
              {/if}
            </div>
            {#if tightenError}<div class="notice error tiny" style="margin-top:8px">{tightenError}</div>{/if}
            {#if tightenPlan}
              {#if tightenPlan.supported}
                <div class="cut-list">
                  {#each tightenPlan.pauses.slice(0, 6) as pause}
                    <div class="cut-row"><span class="mono">{timecode(pause.startS)}</span><span class="truncate">… {pause.context}</span><span class="mono">−{pause.durationS.toFixed(2)}s</span></div>
                  {/each}
                  {#if tightenPlan.pauses.length > 6}<div class="tiny muted">+ {tightenPlan.pauses.length - 6} more pauses</div>{/if}
                </div>
                <div class="row" style="margin-top:10px">
                  <Button size="sm" variant="primary" onclick={applyTighten} disabled={!!edit.subtitles.tighten?.enabled}>Turn on tighten</Button>
                  <span class="tiny muted">Before {tightenPlan.originalDurationS.toFixed(1)}s → after {tightenPlan.plannedDurationS.toFixed(1)}s</span>
                </div>
              {:else}
                <div class="notice tiny" style="margin-top:8px">{tightenPlan.reason}</div>
              {/if}
            {/if}
          </div>
        </div>

        <div class="control-group">
          <h3><Icon name="volume" size={16} /> Audio</h3>
          <div class="stack">
            <div class="field">
              <label for="loudness">Loudness target · {edit.audio.loudnessTarget} LUFS</label>
              <input id="loudness" class="range" type="range" min="-24" max="-10" step="0.5" value={edit.audio.loudnessTarget} oninput={(e) => update('audio', 'loudnessTarget', Number((e.currentTarget as HTMLInputElement).value))} />
            </div>
            <label class="check"><input type="checkbox" checked={edit.audio.voiceEnhance} onchange={(e) => update('audio', 'voiceEnhance', (e.currentTarget as HTMLInputElement).checked)} /><span>Gentle voice enhancement (EQ + light compression)</span></label>
            <label class="check"><input type="checkbox" checked={edit.audio.denoise} onchange={(e) => update('audio', 'denoise', (e.currentTarget as HTMLInputElement).checked)} /><span>Noise reduction</span></label>
            <div class="field">
              <label for="music-path">Background music (optional)</label>
              <div class="row">
                <input id="music-path" class="input mono" readonly value={edit.audio.musicPath || ''} placeholder="No music" />
                <Button size="sm" variant="ghost" onclick={chooseMusic}><Icon name="folder" size={13} /> Choose</Button>
                {#if edit.audio.musicPath}<button class="link tiny" onclick={() => update('audio', 'musicPath', null)}>Remove</button>{/if}
              </div>
            </div>
            <p class="tiny muted">Two-pass loudnorm, true-peak limiting and sidechain ducking when music is present. Pauses, laughter and applause are preserved.</p>
          </div>
        </div>
      </div>
    </div>

    {#if activeJob && ['queued', 'running', 'waiting_rate_limit', 'cancelling'].includes(activeJob.state)}
      <div class="card tight">
        <div class="spread">
          <div class="row">
            <Icon name="loader" size={16} />
            <div>
              <div class="small" style="font-weight:600">{activeJob.progress?.message || 'Rendering…'}</div>
              <div class="tiny muted">{activeJob.progress?.stage || activeJob.stage}</div>
            </div>
          </div>
          <div class="row">
            <span class="mono">{Math.round((activeJob.progress?.fraction || 0) * 100)}%</span>
            <Button size="sm" variant="ghost" onclick={cancelRender}>Cancel</Button>
          </div>
        </div>
        <div class="progress" style="margin-top:10px"><span style={`width:${Math.max(3, (activeJob.progress?.fraction || 0) * 100)}%`}></span></div>
      </div>
    {/if}

    {#if renderError}
      <div class="notice error">
        {renderError}
        <div class="row" style="margin-top:8px">
          {#if activeJob && ['interrupted', 'failed'].includes(activeJob.state)}<Button size="sm" variant="ghost" onclick={resumeRender}>Resume render</Button>{/if}
          <button class="link tiny" onclick={() => (renderError = null)}>Dismiss</button>
        </div>
      </div>
    {/if}

    <div class="card tight">
      <div class="spread" style="margin-bottom:10px">
        <h3>Export queue</h3>
        <span class="tiny muted">{exportsQueue.length} item{exportsQueue.length === 1 ? '' : 's'}</span>
      </div>
      {#if exportsQueue.length}
        <table class="table">
          <thead><tr><th>File</th><th>State</th><th>Checks</th><th></th></tr></thead>
          <tbody>
            {#each exportsQueue as item (item.id)}
              <tr>
                <td class="mono tiny" style="max-width:360px;overflow:hidden;text-overflow:ellipsis">{item.outputPath.split(/[\\/]/).pop()}</td>
                <td><span class={`pill ${item.state === 'succeeded' ? 'success' : item.state === 'failed' ? 'danger' : ''}`}>{item.state}</span></td>
                <td class="tiny muted">{item.ffprobe?.ok ? `${item.ffprobe.width}×${item.ffprobe.height} · ${item.ffprobe.codec}` : (item.error || '—')}</td>
                <td style="text-align:right">
                  {#if item.state === 'succeeded'}<button class="link tiny" onclick={() => showFile(item.outputPath)}>Show file</button>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {:else}
        <p class="small muted">No exports yet. Start one above; the queue records each validation result.</p>
      {/if}
    </div>
  </div>
{/if}
