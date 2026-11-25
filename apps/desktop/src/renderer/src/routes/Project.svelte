<script lang="ts">
  import { tick } from 'svelte'
  import { appState, setRoute, refreshBoot, toast, jobState, trackJob } from '$lib/state.svelte'
  import { request, errorText, errorCode } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import CategoryPill from '$components/CategoryPill.svelte'
  import CandidateCard from '$components/CandidateCard.svelte'
  import MomentMap from '$components/MomentMap.svelte'
  import Player from '$components/Player.svelte'
  import { CATEGORIES, categoryMeta, durationLabel, timecode } from '$lib/categories'
  import type { Candidate, SourceSummary } from '$shared/types'

  let loading = $state(true)
  let error = $state<string | null>(null)
  let project = $state<any>(null)
  let sources = $state<SourceSummary[]>([])
  let source = $state<any>(null)
  let assets = $state<any[]>([])
  let transcript = $state<any>(null)
  let candidates = $state<Candidate[]>([])
  let selections = $state<any[]>([])
  let selectedIds = $state<string[]>([])
  let picked = $state<Candidate | null>(null)
  let playhead = $state(0)
  let player = $state<any>(null)
  let previewUrl = $state<string | null>(null)
  let previewStart = $state(0)
  let previewEnd = $state<number | null>(null)
  let previewOffset = $state(0)
  let previewLoading = $state(false)

  let filterCategory = $state('all')
  let sortBy = $state<'fit' | 'time' | 'duration'>('fit')
  let viewMode = $state<'grid' | 'list'>('grid')
  let search = $state('')

  let showImport = $state(false)
  let importUrl = $state('')
  let importBusy = $state(false)
  let importError = $state<string | null>(null)
  let importAuthorized = $state(Boolean(appState.settings?.privacy.authorizationAcknowledgedAt))

  let engine = $state<'cloud_openai' | 'local_whisper'>('cloud_openai')
  let localModel = $state('small')
  let cloudModel = $state('whisper-large-v3-turbo')
  let preferCaptions = $state(true)
  let models = $state<any[]>([])
  let providerModels = $state<any[]>([])
  let providerProfileId = $state<string | null>(null)
  let analysisModel = $state('')
  let estimate = $state<any>(null)
  let estimateBusy = $state(false)

  let activeJob = $state<any>(null)
  let jobError = $state<string | null>(null)
  let clock = $state(Date.now())

  $effect(() => {
    if (!activeJob || activeJob.state !== 'waiting_rate_limit') return
    clock = Date.now()
    const timer = setInterval(() => (clock = Date.now()), 500)
    return () => clearInterval(timer)
  })

  const waitTarget = $derived.by(() => {
    const progress = activeJob?.progress
    if (progress?.etaSeconds != null) {
      const emittedAt = Number(progress.at || 0) * 1000
      return (emittedAt || clock) + Number(progress.etaSeconds) * 1000
    }
    return Number(activeJob?.resumeAt || 0) * 1000
  })

  const waitSeconds = $derived.by(() =>
    waitTarget ? Math.max(0, Math.ceil((waitTarget - clock) / 1000)) : 0
  )
  let showDisclosure = $state(false)
  let disclosureChecked = $state(false)
  let pendingAnalysis = $state(false)
  let editStart = $state(0)
  let editEnd = $state(0)
  let savingBounds = $state(false)
  let transcriptOpen = $state(true)
  let revisions = $state<any[]>([])
  let compareOpen = $state(false)
  let compareA = $state<string | null>(null)
  let compareB = $state<string | null>(null)
  let compareClips = $state<Record<string, { src: string; start: number; end: number }>>({})
  let compareBusy = $state<Record<string, boolean>>({})
  let compareErrors = $state<Record<string, string>>({})

  const filtered = $derived(
    candidates
      .filter((c) => c.status !== 'rejected')
      .filter((c) => filterCategory === 'all' || c.categories?.includes(filterCategory) || c.category === filterCategory)
      .filter((c) => !search || (c.title + ' ' + c.excerpt + ' ' + c.rationale).toLowerCase().includes(search.toLowerCase()))
      .sort((a, b) => {
        if (sortBy === 'time') return a.startS - b.startS
        if (sortBy === 'duration') return b.durationS - a.durationS
        return b.fitScore - a.fitScore
      })
  )

  const allCategories = $derived([...new Set(candidates.flatMap((c) => c.categories?.length ? c.categories : [c.category]))])
  const selectedCandidates = $derived(candidates.filter((c) => selectedIds.includes(c.id)))
  const defaultProfile = $derived(appState.providers.find((p) => p.id === (appState.defaultProfileId || appState.providers[0]?.id)))
  const sourceThumb = $derived(assets.find((a) => a.kind === 'thumb')?.mediaUrl)
  const transcriptRange = $derived(
    picked
      ? (transcript?.segments || []).filter((s: any) => s.endS > picked!.startS - 2 && s.startS < picked!.endS + 2)
      : []
  )
  const compareLeft = $derived(candidates.find((c) => c.id === compareA) || candidates[0] || null)
  const compareRight = $derived(candidates.find((c) => c.id === compareB) || candidates[1] || null)
  const compareLeftClip = $derived(compareLeft ? compareClips[compareLeft.id] || null : null)
  const compareRightClip = $derived(compareRight ? compareClips[compareRight.id] || null : null)

  $effect(() => {
    if (appState.projectId) load()
  })

  $effect(() => {
    const id = picked?.id
    if (!id) {
      revisions = []
      return
    }
    request('candidates.revisions', { candidateId: id })
      .then((result) => (revisions = result.revisions || []))
      .catch(() => (revisions = []))
  })

  $effect(() => {
    if (picked) {
      editStart = Number(picked.startS.toFixed(2))
      editEnd = Number(picked.endS.toFixed(2))
    }
  })

  $effect(() => {
    if (appState.settings) {
      engine = appState.settings.transcription.engine
      localModel = appState.settings.transcription.localModel
      cloudModel = appState.settings.transcription.cloudModel
      preferCaptions = appState.settings.transcription.preferCaptions
      providerProfileId = appState.settings.transcription.providerProfileId || appState.defaultProfileId
      analysisModel = defaultProfile?.defaultModel || ''
    }
  })

  $effect(() => {
    if (source?.kind === 'url' && !transcript) {
      request('source.get', { sourceId: source.id }).then((r) => {
        assets = r.assets || []
      }).catch(() => undefined)
    }
  })

  async function load() {
    const projectId = appState.projectId
    if (!projectId) return
    loading = true
    error = null
    try {
      const opened = await request('project.open', { projectId })
      project = opened.project
      sources = opened.sources?.length ? opened.sources : opened.project.sources || []
      selections = opened.selections || []
      compareClips = {}
      if (!source || !sources.find((s: SourceSummary) => s.id === source.id)) {
        source = sources[0] || null
      }
      if (source) {
        source = sources.find((s: SourceSummary) => s.id === source.id) || sources[0]
        previewUrl = source.mediaUrl || null
        previewStart = 0
        previewEnd = null
        previewOffset = 0
        await loadSource()
      }
      if (!models.length) {
        const list = await request('models.list').catch(() => null)
        models = list?.items || []
      }
      if (!providerModels.length && defaultProfile) {
        loadProviderModels().catch(() => undefined)
      }
    } catch (err) {
      error = errorText(err)
    } finally {
      loading = false
    }
  }

  async function loadSource() {
    if (!source) return
    const [sourceResult, transcriptResult, candidateResult, selectionResult] = await Promise.all([
      request('source.get', { sourceId: source.id }).catch(() => null),
      request('transcript.get', { sourceId: source.id, includeWords: false }).catch(() => null),
      request('candidates.list', { sourceId: source.id }).catch(() => null),
      request('selection.list', { projectId: appState.projectId }).catch(() => null)
    ])
    if (sourceResult) {
      source = { ...source, ...sourceResult.source }
      assets = sourceResult.assets || []
      if (!previewUrl && sourceResult.source?.mediaUrl) previewUrl = sourceResult.source.mediaUrl
    }
    transcript = transcriptResult?.transcript || null
    candidates = candidateResult?.candidates || []
    selections = selectionResult?.selections || []
    const selectedSet = new Set(selections.map((s: any) => s.candidateId))
    selectedIds = candidates.filter((c) => selectedSet.has(c.id)).map((c) => c.id)
    if (picked) picked = candidates.find((c) => c.id === picked!.id) || null
    if (!picked && candidates.length) await pickCandidate(candidates[0], false)
  }

  async function pickSource(next: SourceSummary) {
    source = next
    transcript = null
    candidates = []
    picked = null
    previewUrl = next.mediaUrl || null
    previewStart = 0
    previewEnd = null
    previewOffset = 0
    compareClips = {}
    await loadSource()
  }

  async function importLocal() {
    const chosen = await window.clipwright.openMediaDialog()
    if (!chosen) return
    importBusy = true
    importError = null
    try {
      await request('source.import_file', { projectId: appState.projectId, path: chosen.path })
      toast('success', 'Source imported.')
      showImport = false
      await load()
      await refreshBoot()
    } catch (err) {
      importError = errorText(err)
    } finally {
      importBusy = false
    }
  }

  async function importFromUrl() {
    importBusy = true
    importError = null
    try {
      const ack = new Date().toISOString()
      await request('settings.set', { key: 'privacy', value: { authorizationAcknowledgedAt: ack } })
      await request('source.import_url', { projectId: appState.projectId, url: importUrl, authorizationAckAt: ack })
      toast('success', 'Source imported.')
      showImport = false
      importUrl = ''
      await load()
      await refreshBoot()
    } catch (err) {
      importError = errorText(err)
    } finally {
      importBusy = false
    }
  }

  async function loadProviderModels() {
    if (!defaultProfile) return
    try {
      const result = await request('provider.list_models', { profileId: defaultProfile.id })
      providerModels = result.models || []
      if (!analysisModel) analysisModel = defaultProfile.defaultModel || providerModels[0]?.id || ''
    } catch {
      providerModels = []
    }
  }

  async function waitForJob(jobId: string): Promise<any> {
    activeJob = jobState.jobs[jobId] || { id: jobId, state: 'queued', progress: {} }
    jobError = null
    while (true) {
      const { job } = await request('jobs.get', { jobId })
      activeJob = job
      trackJob(job)
      if (['succeeded', 'failed', 'cancelled', 'interrupted'].includes(job.state)) {
        if (job.error) jobError = job.error.message
        return job
      }
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
  }

  async function startTranscription() {
    jobError = null
    try {
      const job = await request('transcription.start', {
        sourceId: source.id,
        engine,
        model: engine === 'local_whisper' ? localModel : cloudModel,
        preferCaptions,
        providerProfileId: providerProfileId || defaultProfile?.id
      })
      trackJob({ ...job, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)
      const finished = await waitForJob(job.jobId)
      if (finished.state === 'succeeded') {
        toast('success', 'Transcript ready.')
        const list = await request('models.list').catch(() => null)
        models = list?.items || models
        await loadSource()
      }
    } catch (err) {
      jobError = errorText(err)
    }
  }

  async function resumeJob() {
    if (!activeJob) return
    try {
      await request('jobs.resume', { jobId: activeJob.id })
      const finished = await waitForJob(activeJob.id)
      if (finished.state === 'succeeded') await loadSource()
    } catch (err) {
      jobError = errorText(err)
    }
  }

  async function cancelJob() {
    if (!activeJob) return
    await request('jobs.cancel', { jobId: activeJob.id }).catch((err) => toast('error', errorText(err)))
  }

  async function estimateAnalysis() {
    estimateBusy = true
    try {
      estimate = await request('analysis.estimate', {
        sourceId: source.id,
        providerProfileId: defaultProfile?.id,
        model: analysisModel || undefined
      })
    } catch (err) {
      estimate = null
      toast('error', errorText(err))
    } finally {
      estimateBusy = false
    }
  }

  function askAnalysis() {
    if (!defaultProfile) {
      toast('error', 'Add an AI provider in Settings first.')
      return
    }
    if (!analysisModel) {
      toast('error', 'Choose a model for this provider in Settings.')
      return
    }
    if (!appState.settings?.privacy.providerDisclosureAt) {
      showDisclosure = true
      pendingAnalysis = true
      return
    }
    runAnalysis()
  }

  async function confirmDisclosure() {
    if (!disclosureChecked) return
    await request('settings.set', { key: 'privacy', value: { providerDisclosureAt: new Date().toISOString() } })
    if (appState.settings) appState.settings.privacy.providerDisclosureAt = new Date().toISOString()
    showDisclosure = false
    if (pendingAnalysis) {
      pendingAnalysis = false
      runAnalysis()
    }
  }

  async function runAnalysis() {
    jobError = null
    try {
      const job = await request('analysis.start', {
        sourceId: source.id,
        providerProfileId: defaultProfile?.id,
        model: analysisModel,
        options: {
          maxCandidatesPerWindow: appState.settings?.analysis.maxCandidatesPerWindow || 5,
          rankWithAi: appState.settings?.analysis.rankWithAi ?? true
        }
      })
      trackJob({ ...job, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)
      const finished = await waitForJob(job.jobId)
      if (finished.state === 'succeeded') {
        toast('success', 'Clip moments are ready.')
        await loadSource()
      }
    } catch (err) {
      jobError = errorText(err)
    }
  }

  async function pickCandidate(candidate: Candidate, loadPreview = true) {
    picked = candidate
    if (!loadPreview) return
    playhead = candidate.startS
    previewOffset = 0
    const cached = previewCache.get(candidate.id)
    if (cached) {
      previewUrl = cached.url
      previewStart = cached.start
      previewEnd = cached.end
      previewOffset = cached.offset
      await tick()
      player?.seek(previewStart)
      return
    }
    if (source.kind === 'file' && source.mediaUrl) {
      previewUrl = source.mediaUrl
      previewStart = candidate.startS
      previewEnd = candidate.endS
      await tick()
      player?.seek(previewStart)
      return
    }
    previewLoading = true
    try {
      const result = await request('source.fetch_preview', {
        sourceId: source.id,
        startS: Math.max(0, candidate.startS - 1),
        endS: candidate.endS + 1
      })
      previewUrl = result.mediaUrl
      previewOffset = Number(result.startS ?? Math.max(0, candidate.startS - 1))
      previewStart = Math.max(0, candidate.startS - previewOffset)
      previewEnd = Math.max(previewStart + 0.2, candidate.endS - previewOffset)
      previewCache.set(candidate.id, { url: result.mediaUrl, start: previewStart, end: previewEnd, offset: previewOffset })
      await tick()
      player?.seek(previewStart)
    } catch (err) {
      toast('error', errorText(err))
    } finally {
      previewLoading = false
    }
  }

  let previewCache = new Map<string, { url: string; start: number; end: number | null; offset: number }>()

  function toggleSelect(candidate: Candidate) {
    if (selectedIds.includes(candidate.id)) {
      selectedIds = selectedIds.filter((id) => id !== candidate.id)
    } else {
      selectedIds = [...selectedIds, candidate.id]
    }
  }

  async function makeShorts() {
    if (!selectedCandidates.length) return
    try {
      const result = await request('selection.set', {
        projectId: appState.projectId,
        candidateIds: selectedCandidates.map((c) => c.id),
        presetId: null
      })
      selections = result.selections || []
      toast('success', `${selectedCandidates.length} clip${selectedCandidates.length === 1 ? '' : 's'} moved to the Studio.`)
      setRoute('studio', appState.projectId!)
    } catch (err) {
      toast('error', errorText(err))
    }
  }

  async function undoBounds() {
    if (!picked) return
    try {
      const result = await request('candidates.undo', { candidateId: picked.id })
      picked = result.candidate
      candidates = candidates.map((c) => (c.id === result.candidate.id ? result.candidate : c))
      editStart = result.candidate.startS
      editEnd = result.candidate.endS
      previewCache.delete(picked.id)
      const clips = { ...compareClips }
      delete clips[picked.id]
      compareClips = clips
      await pickCandidate(picked)
      const list = await request('candidates.revisions', { candidateId: picked.id }).catch(() => null)
      revisions = list?.revisions || []
      toast('success', 'Boundary edit undone.')
    } catch (err) {
      toast('error', errorText(err))
    }
  }

  async function ensureCompareClip(candidate: Candidate | null) {
    if (!candidate || compareClips[candidate.id] || compareBusy[candidate.id]) return
    if (source.kind === 'file' && source.mediaUrl) {
      compareClips = { ...compareClips, [candidate.id]: { src: source.mediaUrl, start: candidate.startS, end: candidate.endS } }
      return
    }
    compareBusy = { ...compareBusy, [candidate.id]: true }
    compareErrors = { ...compareErrors, [candidate.id]: '' }
    try {
      const result = await request('source.fetch_preview', {
        sourceId: source.id,
        startS: Math.max(0, candidate.startS - 1),
        endS: candidate.endS + 1
      })
      const offset = Number(result.startS ?? Math.max(0, candidate.startS - 1))
      compareClips = {
        ...compareClips,
        [candidate.id]: {
          src: result.mediaUrl,
          start: Math.max(0, candidate.startS - offset),
          end: Math.max(0.2, candidate.endS - offset)
        }
      }
    } catch (err) {
      compareErrors = { ...compareErrors, [candidate.id]: errorText(err) }
    } finally {
      compareBusy = { ...compareBusy, [candidate.id]: false }
    }
  }

  function retryCompare(candidate: Candidate | null) {
    if (!candidate) return
    const clips = { ...compareClips }
    delete clips[candidate.id]
    compareClips = clips
    ensureCompareClip(candidate)
  }

  function openCompare() {
    const left = picked || candidates[0] || null
    const right = candidates.find((c) => c.id !== left?.id) || null
    compareA = left?.id || null
    compareB = right?.id || null
    compareOpen = true
    ensureCompareClip(left)
    ensureCompareClip(right)
  }

  function setCompare(side: 'left' | 'right', id: string) {
    if (side === 'left') compareA = id
    else compareB = id
    const candidate = candidates.find((c) => c.id === id) || null
    ensureCompareClip(candidate)
  }

  async function saveBounds() {
    if (!picked) return
    if (editEnd <= editStart) {
      toast('error', 'The end must come after the start.')
      return
    }
    savingBounds = true
    try {
      const result = await request('candidates.update_bounds', { candidateId: picked.id, startS: editStart, endS: editEnd })
      picked = result.candidate
      candidates = candidates.map((c) => (c.id === picked!.id ? picked! : c))
      previewCache.delete(picked.id)
      const clips = { ...compareClips }
      delete clips[picked.id]
      compareClips = clips
      await pickCandidate(picked)
      toast('success', 'Boundary saved.')
    } catch (err) {
      toast('error', errorText(err))
    } finally {
      savingBounds = false
    }
  }

  function nudge(delta: number, edge: 'start' | 'end') {
    if (edge === 'start') editStart = Math.max(0, Number((editStart + delta).toFixed(2)))
    else editEnd = Math.max(editStart + 0.1, Number((editEnd + delta).toFixed(2)))
  }

  async function snapWord(edge: 'start' | 'end', direction: 1 | -1) {
    if (!transcript || !source) return
    // Project loads segments without word rows for speed. Fetch them only when
    // the user asks to snap a boundary to a spoken word.
    if (!(transcript.segments || []).some((s: any) => s.words?.length)) {
      const full = await request('transcript.get', { sourceId: source.id, includeWords: true }).catch(() => null)
      if (!full?.transcript) return
      transcript = full.transcript
    }
    const words = (transcript.segments || []).flatMap((s: any) => s.words || [])
    const current = edge === 'start' ? editStart : editEnd
    const candidates = words
      .map((w: any) => ({ time: edge === 'start' ? w.startS : w.endS, text: w.text }))
      .filter((w: any) => direction > 0 ? w.time > current + 0.02 : w.time < current - 0.02)
      .sort((a: any, b: any) => direction > 0 ? a.time - b.time : b.time - a.time)
    if (candidates[0]) {
      if (edge === 'start') editStart = Number(candidates[0].time.toFixed(2))
      else editEnd = Number(candidates[0].time.toFixed(2))
    }
  }

  async function reject(candidate: Candidate) {
    await request('candidates.set_status', { candidateId: candidate.id, status: 'rejected' }).catch((err) => toast('error', errorText(err)))
    candidates = candidates.filter((c) => c.id !== candidate.id)
    selectedIds = selectedIds.filter((id) => id !== candidate.id)
    if (picked?.id === candidate.id) picked = candidates[0] || null
  }

  function onMapSeek(time: number) {
    playhead = time
    if (source?.kind === 'file') {
      player?.seek(time)
    } else {
      player?.seek(Math.max(0, time - previewOffset))
    }
  }

  function onPlayerTime(time: number) {
    playhead = source?.kind === 'file' ? time : time + previewOffset
  }

  function formatEstimate() {
    if (!estimate) return ''
    return `≈ ${estimate.requests} requests · ≈ ${(estimate.estimatedTokens / 1000).toFixed(0)}k tokens · ${estimate.windows} window${estimate.windows === 1 ? '' : 's'}`
  }

  function jobLabel(job: any): string {
    if (!job) return ''
    if (job.state === 'waiting_rate_limit') return job.progress?.message || 'Waiting for the provider rate limit…'
    if (job.state === 'queued') return 'Queued…'
    if (job.state === 'cancelling') return 'Stopping…'
    return job.progress?.message || 'Working…'
  }

  const localModelInstalled = $derived(models.find((m) => m.kind === 'whisper' && m.name === localModel)?.installed)
</script>

{#if loading}
  <div class="page"><div class="empty card"><Icon name="loader" size={28} /><p>Opening the project…</p></div></div>
{:else if error}
  <div class="page"><div class="notice error">{error}</div></div>
{:else if !source}
  <div class="page">
    <header class="page-head">
      <div>
        <div class="eyebrow">Discovery</div>
        <h1 style="margin-top:6px">{project?.name || 'New project'}</h1>
        <p>Bring in a long conversation. Clipwright reads the whole thing before proposing any moment.</p>
      </div>
      <div class="spacer"></div>
      <Button variant="primary" onclick={() => (showImport = true)}><Icon name="plus" size={15} /> Add source</Button>
    </header>
    <div class="empty card">
      <Icon name="upload" size={42} />
      <h3>Nothing to read yet</h3>
      <p>Import a local video or a link you are authorized to use. The transcript comes first; the full video is only fetched where you choose.</p>
      <Button variant="primary" onclick={() => (showImport = true)}>Import a source</Button>
    </div>
  </div>
{:else}
  <div class="page">
    <header class="page-head">
      <div style="min-width:0">
        <div class="row tight">
          <div class="eyebrow">Discovery</div>
          <span class="pill">{source.kind === 'url' ? 'Online source' : 'Local file'}</span>
          {#if source.channel}<span class="pill">{source.channel}</span>{/if}
        </div>
        <h1 style="margin-top:6px;max-width:900px" title={project?.name || source.title}>{project?.name || source.title}</h1>
        <div class="row small muted" style="margin-top:10px">
          <span class="truncate" style="max-width:360px" title={source.title}>{source.title}</span>
          <span class="mono">{timecode(source.durationS || 0)}</span>
          {#if source.width}<span>· {source.width}×{source.height}</span>{/if}
          {#if transcript}<span>· transcript {transcript.origin === 'subtitle' ? 'from captions' : transcript.origin.replace('_', ' ')}</span>{/if}
          {#if transcript?.wordTiming === 'approximate'}<span class="pill warn">approximate word timing</span>{/if}
        </div>
      </div>
      <div class="spacer"></div>
      <div class="row">
        {#if sources.length > 1}
          <select class="select" style="width:220px" value={source.id} onchange={(e) => pickSource(sources.find((s) => s.id === (e.currentTarget as HTMLSelectElement).value)!)}>
            {#each sources as s}<option value={s.id}>{s.title}</option>{/each}
          </select>
        {/if}
        <Button variant="ghost" onclick={() => (showImport = true)}><Icon name="plus" size={14} /> Add source</Button>
      </div>
    </header>

    {#if activeJob && ['queued', 'running', 'waiting_rate_limit', 'cancelling'].includes(activeJob.state)}
      <div class="card tight">
        <div class="spread">
          <div class="row">
            {#if activeJob.state === 'waiting_rate_limit'}
              <span class="dot wait"></span>
            {:else}
              <Icon name="loader" size={16} />
            {/if}
            <div>
              <div class="small" style="font-weight:600">
                {jobLabel(activeJob)}{#if activeJob.state === 'waiting_rate_limit' && waitSeconds > 0}<span class="mono muted" style="margin-left:6px">· {waitSeconds}s</span>{/if}
              </div>
              <div class="tiny muted">{activeJob.progress?.stage?.replace(/_/g, ' ') || activeJob.stage || 'preparing'}</div>
            </div>
          </div>
          <div class="row">
            <span class="mono small">{Math.round((activeJob.progress?.fraction || 0) * 100)}%</span>
            <Button size="sm" variant="ghost" onclick={cancelJob}>Cancel</Button>
          </div>
        </div>
        <div class={`progress ${activeJob.state === 'waiting_rate_limit' ? 'waiting' : ''}`} style="margin-top:12px">
          <span style={`width:${Math.max(3, (activeJob.progress?.fraction || 0) * 100)}%`}></span>
        </div>
        {#if activeJob.state === 'waiting_rate_limit'}
          <div class="tiny muted" style="margin-top:8px">You can close this window. Progress is checkpointed and resumes where it stopped.</div>
        {/if}
      </div>
    {:else if jobError}
      <div class="notice error">
        <div>
          {jobError}
          <div class="row" style="margin-top:8px">
            {#if activeJob && ['interrupted', 'failed'].includes(activeJob.state)}
              <Button size="sm" variant="ghost" onclick={resumeJob}>Resume</Button>
            {/if}
            <button class="link tiny" onclick={() => (jobError = null)}>Dismiss</button>
          </div>
        </div>
      </div>
    {/if}

    {#if !transcript}
      <section class="card raised">
        <div class="card-head">
          <div>
            <div class="eyebrow">Step 1</div>
            <h2 style="margin-top:4px">Get the words first</h2>
            <p class="small muted" style="margin-top:6px">
              Clipwright analyzes the whole conversation from a transcript, never from the full video stream.
              {source.kind === 'url' ? 'Existing captions are preferred when they exist.' : 'A sidecar .vtt or .srt file is used when present.'}
            </p>
          </div>
          <div class="spacer"></div>
          <Icon name="mic" size={30} />
        </div>
        <div class="form-grid">
          <div class="field">
            <span class="label">Transcription engine</span>
            <div class="seg">
              <button class={engine === 'cloud_openai' ? 'active' : ''} onclick={() => (engine = 'cloud_openai')}>Cloud · fast</button>
              <button class={engine === 'local_whisper' ? 'active' : ''} onclick={() => (engine = 'local_whisper')}>Local · private</button>
            </div>
            <span class="tiny muted">
              {engine === 'cloud_openai'
                ? 'Audio chunks are sent to your provider. Best on weak CPUs.'
                : 'Runs on this computer. No audio leaves it.'}
            </span>
          </div>
          {#if engine === 'local_whisper'}
            <div class="field">
              <label for="trans-model">Local model</label>
              <select id="trans-model" class="select" bind:value={localModel}>
                {#each models.filter((m) => m.kind === 'whisper') as model}
                  <option value={model.name}>{model.label} · {model.downloadMb} MB{model.installed ? ' · installed' : ''}</option>
                {/each}
              </select>
              {#if !localModelInstalled}
                <span class="tiny" style="color:var(--warning)">Not installed. <button class="link" onclick={() => setRoute('models')}>Open Model Manager</button></span>
              {:else}
                <span class="tiny muted">Ready.</span>
              {/if}
            </div>
          {:else}
            <div class="field">
              <label for="cloud-model">Speech model</label>
              <select id="cloud-model" class="select" bind:value={cloudModel}>
                <option value="whisper-large-v3-turbo">whisper-large-v3-turbo</option>
                <option value="whisper-large-v3">whisper-large-v3</option>
              </select>
              <span class="tiny muted">Uses your {defaultProfile?.name || 'provider'} key.</span>
            </div>
          {/if}
          <label class="check wide">
            <input type="checkbox" bind:checked={preferCaptions} />
            <span>Prefer captions that came with the source when they exist. You can re-transcribe for better accuracy later.</span>
          </label>
        </div>
        <div class="row" style="margin-top:18px">
          <Button variant="primary" onclick={startTranscription} disabled={activeJob && ['queued','running','waiting_rate_limit'].includes(activeJob.state)}>
            <Icon name="mic" size={15} /> {source.kind === 'url' ? 'Fetch transcript' : 'Transcribe source'}
          </Button>
          <span class="tiny muted">The transcript is cached and reused; changing subtitle style never re-transcribes.</span>
        </div>
      </section>
    {:else}
      <MomentMap
        duration={source.durationS || transcript.segments.at(-1)?.endS || 1}
        {candidates}
        segments={transcript.segments}
        {playhead}
        {selectedIds}
        onSeek={onMapSeek}
        onPick={(c) => c && pickCandidate(c)}
      />

      {#if candidates.length === 0}
        <section class="card raised">
          <div class="card-head">
            <div>
              <div class="eyebrow">Step 2</div>
              <h2 style="margin-top:4px">Find the moments</h2>
              <p class="small muted" style="margin-top:6px">
                The AI reads timestamped transcript windows and returns segment ranges. Python validates every range,
                snaps boundaries to words and finishes sentences before anything reaches you.
              </p>
            </div>
            <div class="spacer"></div>
            <span class="pill">{Math.round((source.durationS || 0) / 60)} min analyzed</span>
          </div>
          <div class="form-grid">
            <div class="field">
              <label for="provider-model">AI model</label>
              <select id="provider-model" class="select" bind:value={analysisModel}>
                {#if analysisModel}<option value={analysisModel}>{analysisModel}</option>{/if}
                {#each providerModels.filter((m) => m.id !== analysisModel) as model}<option value={model.id}>{model.id}</option>{/each}
              </select>
              <span class="tiny muted">{defaultProfile?.name || 'No provider'} · <button class="link" onclick={() => setRoute('settings')}>provider settings</button></span>
            </div>
            <div class="field" style="align-content:end">
              <div class="row">
                <Button variant="ghost" size="sm" onclick={estimateAnalysis} disabled={estimateBusy}>{estimateBusy ? 'Estimating…' : 'Estimate usage'}</Button>
                {#if estimate}<span class="tiny muted">{formatEstimate()}</span>{/if}
              </div>
            </div>
          </div>
          <div class="row" style="margin-top:18px">
            <Button variant="primary" onclick={askAnalysis} disabled={activeJob && ['queued','running','waiting_rate_limit'].includes(activeJob.state)}>
              <Icon name="spark" size={15} /> Analyze the whole source
            </Button>
            {#if !appState.settings?.privacy.providerDisclosureAt}
              <span class="tiny muted">You will see exactly what gets sent before the first analysis.</span>
            {/if}
          </div>
          {#if transcript.origin === 'subtitle'}
            <div class="notice" style="margin-top:14px">
              This transcript came from the source's captions, which may contain recognition errors.
              <button class="link" onclick={async () => {
                const job = await request('transcription.start', { sourceId: source.id, engine, model: engine === 'local_whisper' ? localModel : cloudModel, preferCaptions: false, providerProfileId: defaultProfile?.id })
                trackJob({ ...job, params: {}, checkpoint: {}, createdAt: '', updatedAt: '' } as any)
                const finished = await waitForJob(job.jobId)
                if (finished.state === 'succeeded') await loadSource()
              }}>Re-transcribe from audio</button>
            </div>
          {/if}
        </section>
      {:else}
        <div class="row" style="justify-content:space-between">
          <div class="row">
            <span class="eyebrow">{candidates.length} moments</span>
            <span class="tiny muted">sorted by clip fit</span>
          </div>
          <div class="row">
            <input class="input" bind:value={search} placeholder="Search moments" style="width:200px" aria-label="Search moments" />
            <select class="select" bind:value={sortBy} style="width:150px" aria-label="Sort moments">
              <option value="fit">Clip fit</option>
              <option value="time">Time</option>
              <option value="duration">Duration</option>
            </select>
            <div class="seg">
              <button class={viewMode === 'grid' ? 'active' : ''} onclick={() => (viewMode = 'grid')}>Grid</button>
              <button class={viewMode === 'list' ? 'active' : ''} onclick={() => (viewMode = 'list')}>List</button>
            </div>
            {#if candidates.length > 1}
              <Button size="sm" variant="ghost" onclick={openCompare}><Icon name="split" size={13} /> Compare</Button>
            {/if}
          </div>
        </div>

        <div class="row" style="gap:8px">
          <button class={`pill ${filterCategory === 'all' ? 'gold' : ''}`} onclick={() => (filterCategory = 'all')}>All</button>
          {#each allCategories as cat}
            <button class={`pill cat ${filterCategory === cat ? 'active' : ''}`} style={`--cat-color:${categoryMeta(cat).color};${filterCategory === cat ? 'outline:1px solid currentColor' : ''}`} onclick={() => (filterCategory = cat)}>
              {categoryMeta(cat).label}
            </button>
          {/each}
        </div>

        <div class="panel-grid">
          <div class={viewMode === 'grid' ? 'candidate-grid' : 'stack'} style={viewMode === 'grid' ? 'grid-template-columns:1fr' : ''}>
            {#each filtered as candidate (candidate.id)}
              <CandidateCard
                {candidate}
                selected={selectedIds.includes(candidate.id)}
                onToggle={toggleSelect}
                onPreview={pickCandidate}
                onReject={reject}
              />
            {/each}
            {#if !filtered.length}
              <div class="empty card"><h3>No moments match this filter</h3><p>Try another category or clear the search.</p></div>
            {/if}
          </div>

          <aside class="stack" style="position:sticky;top:0">
            <div class="card tight">
              <div class="row" style="justify-content:space-between;margin-bottom:10px">
                <div>
                  <div class="eyebrow">Preview</div>
                  <div class="small" style="font-weight:600">{picked?.title || 'Pick a moment'}</div>
                </div>
                {#if picked}<span class="pill gold">fit {Math.round(picked.fitScore)}</span>{/if}
              </div>
              {#if previewLoading}
                <div class="empty" style="padding:40px"><Icon name="loader" size={24} /><p>Fetching just this section…</p></div>
              {:else}
                <Player bind:this={player} src={previewUrl} startS={previewStart} endS={previewEnd} onTime={onPlayerTime} label="The clip preview" />
              {/if}
              {#if picked}
                <div class="row tiny muted" style="margin-top:10px;justify-content:space-between">
                  <span class="mono">{timecode(picked.startS, true)} → {timecode(picked.endS, true)}</span>
                  <span>{durationLabel(picked.durationS)}</span>
                </div>
              {/if}
            </div>

            {#if picked}
              <div class="card tight">
                <div class="spread" style="margin-bottom:10px">
                  <h3>Boundaries</h3>
                  <span class="tiny muted">snapped to spoken words</span>
                </div>
                <div class="form-grid" style="grid-template-columns:1fr 1fr">
                  <div class="field">
                    <label for="start-s">Start (s)</label>
                    <input id="start-s" class="input mono" type="number" step="0.05" bind:value={editStart} />
                    <div class="row tight">
                      <button class="tag" onclick={() => snapWord('start', -1)}>− word</button>
                      <button class="tag" onclick={() => nudge(-0.1, 'start')}>−0.1</button>
                      <button class="tag" onclick={() => nudge(0.1, 'start')}>+0.1</button>
                      <button class="tag" onclick={() => snapWord('start', 1)}>+ word</button>
                    </div>
                  </div>
                  <div class="field">
                    <label for="end-s">End (s)</label>
                    <input id="end-s" class="input mono" type="number" step="0.05" bind:value={editEnd} />
                    <div class="row tight">
                      <button class="tag" onclick={() => snapWord('end', -1)}>− word</button>
                      <button class="tag" onclick={() => nudge(-0.1, 'end')}>−0.1</button>
                      <button class="tag" onclick={() => nudge(0.1, 'end')}>+0.1</button>
                      <button class="tag" onclick={() => snapWord('end', 1)}>+ word</button>
                    </div>
                  </div>
                </div>
                <div class="row" style="margin-top:12px">
                  <Button size="sm" variant="primary" onclick={saveBounds} disabled={savingBounds}>{savingBounds ? 'Saving…' : 'Save boundaries'}</Button>
                  <Button size="sm" variant="ghost" onclick={undoBounds} disabled={!revisions.length}>Undo</Button>
                  <span class="tiny muted">{revisions.length ? `${revisions.length} earlier edit${revisions.length === 1 ? '' : 's'} kept` : 'Boundary edits are kept as revisions'}</span>
                </div>
              </div>

              <div class="card tight">
                <div class="spread" style="margin-bottom:8px">
                  <h3>Transcript around the clip</h3>
                  <button class="link tiny" onclick={() => (transcriptOpen = !transcriptOpen)}>{transcriptOpen ? 'Hide' : 'Show'}</button>
                </div>
                {#if transcriptOpen}
                  <div style="max-height:230px;overflow:auto;display:grid;gap:8px">
                    {#each transcriptRange as seg}
                      {@const inRange = seg.endS > picked.startS && seg.startS < picked.endS}
                      {@const active = playhead >= seg.startS && playhead < seg.endS}
                      <button
                        class="small"
                        style={`text-align:left;background:${active ? 'var(--accent-soft)' : inRange ? 'var(--surface-2)' : 'transparent'};border-left:2px solid ${active ? 'var(--accent)' : 'transparent'};border-radius:8px;padding:8px 10px;color:${inRange ? 'var(--text)' : 'var(--muted)'}`}
                        onclick={() => onMapSeek(seg.startS)}
                      >
                        <span class="mono tiny" style="color:var(--faint);margin-right:8px">{timecode(seg.startS)}</span>
                        {seg.text}
                      </button>
                    {/each}
                  </div>
                {/if}
              </div>
            {/if}
          </aside>
        </div>

        {#if selectedIds.length}
          <div class="selection-tray">
            <span class="pill gold">{selectedIds.length} selected</span>
            <div class="row tight" style="flex:1;overflow:hidden">
              {#each selectedCandidates.slice(0, 3) as c}
                <span class="tag truncate" style="max-width:220px">{c.title}</span>
              {/each}
              {#if selectedCandidates.length > 3}<span class="tiny muted">+{selectedCandidates.length - 3} more</span>{/if}
            </div>
            <Button variant="primary" onclick={makeShorts}><Icon name="scissors" size={15} /> Make Short{selectedCandidates.length > 1 ? 's' : ''} ({selectedCandidates.length})</Button>
          </div>
        {/if}
      {/if}
    {/if}
  </div>
{/if}

{#if compareOpen}
  <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (compareOpen = false)} role="presentation">
    <div class="modal compare-modal" role="dialog" aria-modal="true" aria-labelledby="compare-title">
      <div class="spread">
        <div>
          <div class="eyebrow">Side by side</div>
          <h2 id="compare-title">Compare moments</h2>
        </div>
        <button class="icon-btn" onclick={() => (compareOpen = false)} aria-label="Close compare"><Icon name="x" size={16} /></button>
      </div>
      <div class="compare-grid">
        {#each [compareLeft, compareRight] as candidate, i}
          <div class="stack">
            <select class="select" value={candidate?.id || ''} onchange={(e) => setCompare(i === 0 ? 'left' : 'right', (e.currentTarget as HTMLSelectElement).value)}>
              {#each candidates as option}<option value={option.id}>{option.title}</option>{/each}
            </select>
            {#if candidate}
              {@const clip = i === 0 ? compareLeftClip : compareRightClip}
              <div class="row tight">
                <span class="pill gold">Fit {Math.round(candidate.fitScore)}</span>
                <span class="mono tiny muted">{timecode(candidate.startS)} → {timecode(candidate.endS)}</span>
              </div>
              {#if clip}
                <Player src={clip.src} startS={clip.start} endS={clip.end} label="Compare preview" />
              {:else if compareErrors[candidate.id]}
                <div class="notice error">
                  {compareErrors[candidate.id]}
                  <Button size="sm" variant="ghost" onclick={() => retryCompare(candidate)}>Retry</Button>
                </div>
              {:else}
                <div class="empty card"><p class="small muted"><Icon name="loader" size={16} /> Fetching this preview…</p></div>
              {/if}
              <p class="small muted">{candidate.rationale}</p>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  </div>
{/if}

{#if showImport}
  <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (showImport = false)} role="presentation">
    <div class="modal" role="dialog" aria-modal="true">
      <div>
        <div class="eyebrow">Add source</div>
        <h2>Bring in another</h2>
      </div>
      <button class="dropzone" onclick={importLocal} disabled={importBusy}>
        <Icon name="upload" size={38} />
        <h3>Choose a local video</h3>
        <p class="small muted">Read directly from disk. Nothing is uploaded.</p>
      </button>
      <div class="notice warn">
        Only import content you own or are authorized to reuse. A reachable link is not permission to republish.
      </div>
      {#if !importAuthorized}
        <label class="check">
          <input type="checkbox" bind:checked={importAuthorized} />
          <span>I own this content or have permission to reuse it.</span>
        </label>
      {/if}
      <div class="field">
        <label for="import-url">Or import a link</label>
        <div class="row">
          <input id="import-url" class="input mono" bind:value={importUrl} placeholder="https://…" />
          <Button variant="ghost" onclick={importFromUrl} disabled={importBusy || !importUrl.trim() || !importAuthorized}>{importBusy ? 'Working…' : 'Import'}</Button>
        </div>
      </div>
      {#if importError}
        <div class="notice error">
          {importError}
          <button class="link" onclick={importLocal}>Import a local file instead</button>
        </div>
      {/if}
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (showImport = false)}>Close</Button>
      </div>
    </div>
  </div>
{/if}

{#if showDisclosure}
  <div class="drawer-backdrop" role="presentation">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="disclosure-title">
      <div>
        <div class="eyebrow">Before the first analysis</div>
        <h2 id="disclosure-title">What gets sent</h2>
      </div>
      <div class="stack small soft">
        <div class="muted-box">
          <div class="row"><Icon name="text" size={16} /><span>Transcript windows with timestamps and segment IDs</span></div>
          <div class="row" style="margin-top:8px"><Icon name="spark" size={16} /><span>Clip titles, excerpts and metadata generated during analysis</span></div>
          <div class="row" style="margin-top:8px"><Icon name="mic" size={16} /><span>Audio chunks only if you chose cloud transcription</span></div>
        </div>
        <p>Provider: <strong style="color:var(--text)">{defaultProfile?.name || '—'}</strong> · Model: <strong style="color:var(--text)">{analysisModel || '—'}</strong></p>
        <p>Clipwright never sends whole videos, local files wholesale, or anything on its own initiative.</p>
      </div>
      <label class="check">
        <input type="checkbox" bind:checked={disclosureChecked} />
        <span>I understand and want to analyze this transcript with this provider.</span>
      </label>
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => { showDisclosure = false; pendingAnalysis = false }}>Not now</Button>
        <Button variant="primary" disabled={!disclosureChecked} onclick={confirmDisclosure}>Analyze</Button>
      </div>
    </div>
  </div>
{/if}
