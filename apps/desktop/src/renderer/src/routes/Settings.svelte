<script lang="ts">
  import { appState, saveSettings, refreshBoot, applyAppearance, setRoute, toast } from '$lib/state.svelte'
  import { checkForUpdates, updates } from '$lib/updates.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import { bytesLabel, durationLabel } from '$lib/categories'
  import type { ProviderProfile } from '$shared/types'

  let { onRerunWizard }: { onRerunWizard: () => void } = $props()

  let providerModal = $state<null | { mode: 'add' | 'edit'; profile: any }>(null)
  let keyModal = $state<ProviderProfile | null>(null)
  let keyValue = $state('')
  let allowWeak = $state(false)
  let secretStatus = $state<any>(null)
  let testingId = $state<string | null>(null)
  let providerError = $state<string | null>(null)
  let providerResult = $state<any>(null)
  let busy = $state(false)
  let hardware = $state<any>(null)
  let models = $state<any[]>([])
  let requestLog = $state<any[]>([])
  let binaries = $state<any>(null)
  let binariesBusy = $state(false)
  let diagnosticsPath = $state<string | null>(null)
  let deleteTarget = $state<ProviderProfile | null>(null)

  let transcriptionEngine = $state<'cloud_openai' | 'local_whisper'>('cloud_openai')
  let localModel = $state('small')
  let cloudModel = $state('whisper-large-v3-turbo')
  let speechProvider = $state<string | null>(null)
  let preferCaptions = $state(true)
  let analysis = $state({ maxCandidatesPerWindow: 5, windowSeconds: 360, overlap: 0.22, minDuration: 15, maxDuration: 90, batchSize: 2, rankWithAi: true, visionEnabled: false })
  let outputDir = $state('')
  let hardwareProfile = $state('auto')
  let requestLogEnabled = $state(true)
  let cookiesFile = $state('')

  const themes = [
    { id: 'velvet', name: 'Velvet', color: '#d8a54b', note: 'Graphite with a brass cut.' },
    { id: 'ember', name: 'Ember', color: '#c98152', note: 'Warm brown-black with copper.' },
    { id: 'ivory', name: 'Ivory', color: '#2f5668', note: 'Warm paper with ink blue.' },
    { id: 'slate', name: 'Slate', color: '#84aeb8', note: 'Cool neutral with blue-grey.' }
  ]

  $effect(() => {
    if (appState.settings) {
      const s = appState.settings
      transcriptionEngine = s.transcription.engine
      localModel = s.transcription.localModel
      cloudModel = s.transcription.cloudModel
      speechProvider = s.transcription.providerProfileId || appState.defaultProfileId
      preferCaptions = s.transcription.preferCaptions
      analysis = { batchSize: 2, ...s.analysis }
      outputDir = s.render.outputDir || ''
      hardwareProfile = s.hardware.profile || 'auto'
      requestLogEnabled = s.privacy.requestLogEnabled
      cookiesFile = s.downloads?.cookiesFile || ''
    }
  })

  $effect(() => {
    loadPeripherals()
  })

  async function loadPeripherals() {
    const [hw, modelList, secrets, bin, log] = await Promise.all([
      request('hardware.detect').catch(() => null),
      request('models.list').catch(() => null),
      window.clipwright.secretStatus().catch(() => null),
      request('binaries.status').catch(() => null),
      request('privacy.log').catch(() => null)
    ])
    hardware = hw
    models = modelList?.items || []
    secretStatus = secrets
    binaries = bin
    requestLog = log?.entries || []
  }

  async function patch(key: string, value: Record<string, any>) {
    try {
      await saveSettings(key, value)
      if (key === 'app') applyAppearance()
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  function setTheme(theme: string) {
    if (!appState.settings) return
    patch('app', { theme })
    appState.settings.app.theme = theme as any
    applyAppearance()
  }

  function setAppearance(appearance: 'dark' | 'light') {
    if (!appState.settings) return
    patch('app', { appearance })
    appState.settings.app.appearance = appearance
    applyAppearance()
  }

  function openAdd() {
    providerError = null
    providerResult = null
    providerModal = {
      mode: 'add',
      profile: { name: '', adapter: 'openai_compatible', baseUrl: 'https://', defaultModel: '', capabilities: {} }
    }
  }

  function openEdit(profile: ProviderProfile) {
    providerError = null
    providerResult = null
    providerModal = { mode: 'edit', profile: { ...profile } }
  }

  async function saveProvider() {
    if (!providerModal) return
    busy = true
    providerError = null
    try {
      const profile = providerModal.profile
      const result = await request('provider.save', {
        profile: {
          id: profile.id,
          name: profile.name,
          adapter: profile.adapter,
          baseUrl: profile.baseUrl,
          defaultModel: profile.defaultModel,
          capabilities: profile.capabilities,
          enabled: true
        }
      })
      await refreshBoot()
      toast('success', 'Provider saved.')
      providerModal = null
      if (result.provider?.defaultModel === null) await loadPeripherals()
    } catch (error) {
      providerError = errorText(error)
    } finally {
      busy = false
    }
  }

  function askKey(profile: ProviderProfile) {
    keyModal = profile
    keyValue = ''
    providerError = null
    providerResult = null
  }

  async function saveKey(test = false) {
    if (!keyModal) return
    const profile = keyModal
    busy = true
    providerError = null
    try {
      const result = await window.clipwright.setSecret(profile.id, keyValue, allowWeak)
      await loadPeripherals()
      keyValue = ''
      if (result.sessionOnly) {
        toast('info', 'The keyring is unavailable; the key is kept for this session only.')
      } else {
        toast('success', 'Key stored securely.')
      }
      keyModal = null
      if (test) await testProvider(profile)
    } catch (error) {
      providerError = errorText(error)
    } finally {
      busy = false
    }
  }

  async function testProvider(profile: ProviderProfile, keepKey = false) {
    testingId = profile.id
    providerError = null
    providerResult = null
    try {
      const result = await request('provider.test', { profileId: profile.id, probe: true })
      providerResult = result
      await refreshBoot()
      await loadPeripherals()
      toast('success', `Connection ok · ${result.modelCount} models · ${result.capabilities?.supportsJsonSchemaStrict || result.capabilities?.supports_json_schema_strict ? 'strict schema' : 'best-effort schema'}`)
    } catch (error) {
      providerError = errorText(error)
    } finally {
      testingId = null
    }
  }

  async function makeDefault(profile: ProviderProfile) {
    await saveSettings('providers', { defaultProfileId: profile.id })
    await refreshBoot()
    toast('success', `${profile.name} is now the default provider.`)
  }

  async function removeProvider() {
    if (!deleteTarget) return
    busy = true
    try {
      await request('provider.delete', { profileId: deleteTarget.id })
      await window.clipwright.deleteSecret(deleteTarget.id).catch(() => null)
      await refreshBoot()
      await loadPeripherals()
      deleteTarget = null
      toast('success', 'Provider removed.')
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      busy = false
    }
  }

  async function chooseOutput() {
    const folder = await window.clipwright.chooseFolder()
    if (!folder) return
    outputDir = folder.path
    await patch('render', { outputDir })
  }

  async function chooseCookies() {
    const file = await window.clipwright.openCookiesDialog()
    if (!file) return
    cookiesFile = file.path
    await patch('downloads', { cookiesFile: file.path })
  }

  async function clearCookies() {
    cookiesFile = ''
    await patch('downloads', { cookiesFile: null })
  }

  async function updateDownloader() {
    binariesBusy = true
    try {
      const result = await request('binaries.update', { channel: 'stable' })
      toast('success', `Downloader updated to ${result.version}.`)
      await loadPeripherals()
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      binariesBusy = false
    }
  }

  async function exportDiagnostics() {
    try {
      const result = await request('diagnostics.export')
      diagnosticsPath = result.path
      toast('success', `Diagnostics saved (${bytesLabel(result.bytes)}). No keys, media or transcripts included.`)
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  async function clearLog() {
    await request('privacy.clear')
    requestLog = []
    toast('success', 'Request log cleared.')
  }

  const localInstalled = $derived(models.find((m) => m.kind === 'whisper' && m.name === localModel)?.installed)
</script>

<div class="page">
  <header class="page-head">
    <div>
      <div class="eyebrow">Preferences</div>
      <h1 style="margin-top:6px">Settings</h1>
      <p>Keys live in the operating system's secure storage. The project database never holds them.</p>
    </div>
    <div class="spacer"></div>
    <Button variant="ghost" onclick={onRerunWizard}><Icon name="spark" size={14} /> Run setup wizard</Button>
  </header>

  <div class="panel-grid">
    <div class="stack">
      <section class="card">
        <div class="card-head">
          <div>
            <div class="eyebrow">AI providers</div>
            <h2 style="margin-top:4px">Your keys, your endpoints</h2>
            <p class="small muted" style="margin-top:6px">Groq is pre-added. Any OpenAI-compatible endpoint works, including local Ollama or LM Studio. Qwen 0.6B can also run fully offline; install it in Model Manager.</p>
          </div>
          <div class="spacer"></div>
          <Button size="sm" variant="primary" onclick={openAdd}><Icon name="plus" size={13} /> Add provider</Button>
        </div>
        <div class="list">
          {#each appState.providers as profile (profile.id)}
            <div class="list-item" style="align-items:flex-start">
              <div style="width:38px;height:38px;border-radius:12px;background:var(--surface-3);display:grid;place-items:center">
                <Icon name="key" size={16} />
              </div>
              <div class="grow" style="display:grid;gap:4px">
                <div class="row">
                  <strong class="small">{profile.name}</strong>
                  {#if profile.id === (appState.defaultProfileId || appState.providers[0]?.id)}<span class="pill gold">Default</span>{/if}
                  {#if secretStatus?.storedProfiles?.includes(profile.id)}<span class="pill success">key stored</span>{/if}
                  {#if secretStatus?.sessionProfiles?.includes(profile.id)}<span class="pill warn">session key</span>{/if}
                  {#if profile.envKeyAvailable}<span class="pill">env key</span>{/if}
                  {#if profile.adapter === 'local'}<span class="pill">no key</span>{/if}
                </div>
                <div class="tiny muted mono">{profile.baseUrl}</div>
                <div class="tiny muted">model: {profile.defaultModel || 'not chosen'} · {profile.adapter}</div>
              </div>
              <div class="row tight" style="justify-content:flex-end;max-width:280px">
                {#if profile.adapter !== 'local'}<Button size="sm" variant="ghost" onclick={() => askKey(profile)}>Key</Button>{/if}
                <Button size="sm" variant="ghost" onclick={() => testProvider(profile)} disabled={testingId === profile.id}>
                  {testingId === profile.id ? 'Testing…' : 'Test'}
                </Button>
                {#if profile.adapter !== 'local'}<Button size="sm" variant="ghost" onclick={() => openEdit(profile)}>Edit</Button>{/if}
                {#if profile.id !== (appState.defaultProfileId || appState.providers[0]?.id)}
                  <Button size="sm" variant="ghost" onclick={() => makeDefault(profile)}>Make default</Button>
                {/if}
                <button class="icon-btn" style="width:32px;height:32px" title="Delete provider" onclick={() => (deleteTarget = profile)}><Icon name="trash" size={13} /></button>
              </div>
            </div>
          {/each}
        </div>
        {#if providerError}
          <div class="notice error" style="margin-top:14px">
            {providerError}
            <details><summary>Technical details</summary><pre class="log-tail">{JSON.stringify(providerResult?.probeError || {}, null, 2)}</pre></details>
          </div>
        {/if}
        {#if providerResult}
          <div class="notice gold" style="margin-top:14px">
            {providerResult.modelCount} models · latency {Math.round(providerResult.latencyMs)} ms ·
            strict schema {providerResult.capabilities?.supportsJsonSchemaStrict || providerResult.capabilities?.supports_json_schema_strict ? 'yes' : 'no'} ·
            JSON object {providerResult.capabilities?.supportsJsonObject || providerResult.capabilities?.supports_json_object ? 'yes' : 'no'}
          </div>
        {/if}
      </section>

      <section class="card">
        <div class="card-head">
          <div>
            <div class="eyebrow">Transcription</div>
            <h2 style="margin-top:4px">Two engines, one transcript</h2>
          </div>
          <div class="spacer"></div>
          <Button size="sm" variant="ghost" onclick={() => (window.location.hash = '#/models')}>Model Manager</Button>
        </div>
        <div class="choice-grid">
          <button class={`choice ${transcriptionEngine === 'cloud_openai' ? 'active' : ''}`} onclick={() => { transcriptionEngine = 'cloud_openai'; patch('transcription', { engine: 'cloud_openai' }) }}>
            <h3><Icon name="cloud" size={17} /> Cloud</h3>
            <p>Fast on weak CPUs. Audio chunks up to 10 minutes at 16 kHz mono are sent to the chosen speech provider.</p>
          </button>
          <button class={`choice ${transcriptionEngine === 'local_whisper' ? 'active' : ''}`} onclick={() => { transcriptionEngine = 'local_whisper'; patch('transcription', { engine: 'local_whisper' }) }}>
            <h3><Icon name="mic" size={17} /> Local</h3>
            <p>Private, quota-free, slower. The model is loaded only for the run and released afterwards.</p>
          </button>
        </div>
        <div class="form-grid" style="margin-top:16px">
          <div class="field">
            <label for="local-model-settings">Local model</label>
            <select id="local-model-settings" class="select" bind:value={localModel} onchange={() => patch('transcription', { localModel })}>
              {#each models.filter((m) => m.kind === 'whisper') as model}
                <option value={model.name}>{model.label.split(' (')[0]} · {model.downloadMb} MB</option>
              {/each}
            </select>
            {#if !localInstalled}<span class="tiny" style="color:var(--warning)">Not installed. Download it in Model Manager.</span>{/if}
          </div>
          <div class="field">
            <label for="cloud-model-settings">Cloud speech model</label>
            <select id="cloud-model-settings" class="select" bind:value={cloudModel} onchange={() => patch('transcription', { cloudModel })}>
              <option value="whisper-large-v3-turbo">whisper-large-v3-turbo</option>
              <option value="whisper-large-v3">whisper-large-v3</option>
            </select>
          </div>
          <div class="field">
            <label for="speech-provider">Speech provider</label>
            <select id="speech-provider" class="select" bind:value={speechProvider} onchange={() => patch('transcription', { providerProfileId: speechProvider })}>
              {#each appState.providers as p}<option value={p.id}>{p.name}</option>{/each}
            </select>
          </div>
          <label class="check" style="align-self:end">
            <input type="checkbox" bind:checked={preferCaptions} onchange={() => patch('transcription', { preferCaptions })} />
            <span>Prefer existing captions</span>
          </label>
        </div>
      </section>

      <section class="card">
        <div class="eyebrow">Clip discovery</div>
        <h2 style="margin-top:4px">How aggressively to look</h2>
        <div class="form-grid" style="margin-top:16px">
          <div class="field">
            <label for="max-candidates">Candidates per window</label>
            <input id="max-candidates" class="input" type="number" min="1" max="10" bind:value={analysis.maxCandidatesPerWindow} onchange={() => patch('analysis', { maxCandidatesPerWindow: analysis.maxCandidatesPerWindow })} />
          </div>
          <div class="field">
            <label for="window-s">Window length (seconds)</label>
            <input id="window-s" class="input" type="number" min="90" max="900" step="30" bind:value={analysis.windowSeconds} onchange={() => patch('analysis', { windowSeconds: analysis.windowSeconds })} />
          </div>
          <div class="field">
            <label for="batch-size">Windows per request</label>
            <input id="batch-size" class="input" type="number" min="1" max="4" bind:value={analysis.batchSize} onchange={() => patch('analysis', { batchSize: analysis.batchSize })} />
            <span class="tiny muted">2 reduces repeated prompts and rate-limit pressure. 1 is the most conservative for very tight context.</span>
          </div>
          <div class="field">
            <label for="min-d">Minimum clip (seconds)</label>
            <input id="min-d" class="input" type="number" min="5" max="60" bind:value={analysis.minDuration} onchange={() => patch('analysis', { minDuration: analysis.minDuration })} />
          </div>
          <div class="field">
            <label for="max-d">Maximum clip (seconds)</label>
            <input id="max-d" class="input" type="number" min="30" max="180" bind:value={analysis.maxDuration} onchange={() => patch('analysis', { maxDuration: analysis.maxDuration })} />
          </div>
          <label class="check wide">
            <input type="checkbox" bind:checked={analysis.rankWithAi} onchange={() => patch('analysis', { rankWithAi: analysis.rankWithAi })} />
            <span>Let the AI compare and rank candidates after validation. If it fails, deterministic clip fit decides.</span>
          </label>
        </div>
      </section>

      <section class="card">
        <div class="eyebrow">Appearance</div>
        <h2 style="margin-top:4px">The room</h2>
        <div class="choice-grid" style="margin-top:16px">
          {#each themes as theme}
            <button class={`choice ${appState.settings?.app.theme === theme.id ? 'active' : ''}`} onclick={() => setTheme(theme.id)}>
              <h3><span style={`width:12px;height:12px;border-radius:50%;background:${theme.color};display:inline-block`}></span>{theme.name}</h3>
              <p>{theme.note}</p>
            </button>
          {/each}
        </div>
        <div class="row" style="margin-top:16px">
          <div class="seg">
            <button class={appState.settings?.app.appearance === 'dark' ? 'active' : ''} onclick={() => setAppearance('dark')}>Dark</button>
            <button class={appState.settings?.app.appearance === 'light' ? 'active' : ''} onclick={() => setAppearance('light')}>Light</button>
          </div>
          <div class="seg">
            <button class={appState.settings?.app.density === 'comfortable' ? 'active' : ''} onclick={() => { patch('app', { density: 'comfortable' }); appState.settings!.app.density = 'comfortable'; applyAppearance() }}>Comfortable</button>
            <button class={appState.settings?.app.density === 'compact' ? 'active' : ''} onclick={() => { patch('app', { density: 'compact' }); appState.settings!.app.density = 'compact'; applyAppearance() }}>Compact</button>
          </div>
          <label class="check">
            <input type="checkbox" checked={appState.settings?.app.reduceMotion} onchange={(e) => { const v = (e.currentTarget as HTMLInputElement).checked; patch('app', { reduceMotion: v }); appState.settings!.app.reduceMotion = v; applyAppearance() }} />
            <span>Reduce motion</span>
          </label>
          <label class="check">
            <input type="checkbox" checked={appState.settings?.app.effects} onchange={(e) => { const v = (e.currentTarget as HTMLInputElement).checked; patch('app', { effects: v }); appState.settings!.app.effects = v }} />
            <span>Interface effects</span>
          </label>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <div>
            <div class="eyebrow">Storage & privacy</div>
            <h2 style="margin-top:4px">What leaves this computer</h2>
          </div>
          <div class="spacer"></div>
          <Button size="sm" variant="ghost" onclick={exportDiagnostics}>Export diagnostics</Button>
        </div>
        <div class="muted-box">
          <div class="eyebrow">Data directory</div>
          <div class="mono small" style="margin-top:4px">{appState.settings?.dataDir || appState.appInfo?.userData}</div>
          {#if hardware}<div class="tiny muted" style="margin-top:6px">{bytesLabel(hardware.freeDiskBytes)} free on this volume.</div>{/if}
        </div>
        <div class="field" style="margin-top:14px">
          <label for="output-folder">Default output folder</label>
          <div class="row">
            <input id="output-folder" class="input mono" readonly value={outputDir} />
            <Button size="sm" variant="ghost" onclick={chooseOutput}><Icon name="folder" size={13} /> Choose</Button>
          </div>
        </div>
        {#if diagnosticsPath}<div class="notice" style="margin-top:10px">{diagnosticsPath}</div>{/if}
        <div class="muted-box" style="margin-top:14px">
          <div class="eyebrow">What gets sent</div>
          <div class="stack tiny muted" style="margin-top:8px">
            <span>• Transcript windows with timestamps and segment IDs</span>
            <span>• Clip titles, excerpts, rationales and generated metadata</span>
            <span>• Audio chunks only when cloud transcription is selected</span>
            <span>• Never whole videos, never local files wholesale, never anything on the app's own initiative</span>
          </div>
        </div>
        <div class="row" style="margin-top:16px;justify-content:space-between">
          <div>
            <h3>Request log</h3>
            <p class="tiny muted">Metadata only. Never transcript text, audio or keys.</p>
          </div>
          <div class="row">
            <label class="check"><input type="checkbox" bind:checked={requestLogEnabled} onchange={() => patch('privacy', { requestLogEnabled })} /><span>Record</span></label>
            <Button size="sm" variant="ghost" onclick={clearLog}>Clear log</Button>
          </div>
        </div>
        {#if requestLog.length}
          <div style="max-height:240px;overflow:auto;margin-top:10px">
            <table class="table">
              <thead><tr><th>Time</th><th>Provider</th><th>Operation</th><th>Tokens</th><th>Outcome</th></tr></thead>
              <tbody>
                {#each requestLog.slice(0, 40) as entry}
                  <tr><td class="muted tiny">{new Date(entry.at).toLocaleString()}</td><td class="small">{entry.provider}</td><td class="small">{entry.operation}</td><td class="mono">{entry.approxTokens}</td><td><span class={`pill ${entry.outcome === 'ok' ? 'success' : 'warn'}`}>{entry.outcome}</span></td></tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <p class="small muted" style="margin-top:10px">No requests recorded yet.</p>
        {/if}
      </section>
    </div>

    <div class="stack">
      <section class="card">
        <div class="eyebrow">Hardware</div>
        <h2 style="margin-top:4px">What this machine can do</h2>
        {#if hardware}
          <div class="stack" style="margin-top:14px">
            <div><div class="eyebrow">CPU</div><div class="small">{hardware.cpuModel || 'Unknown'}</div><div class="tiny muted">{hardware.cores} logical cores · {bytesLabel(hardware.ramBytes)} RAM</div></div>
            <div><div class="eyebrow">GPU</div><div class="small">{hardware.gpus.length ? hardware.gpus.map((g: any) => g.name).join(', ') : 'None detected'}</div><div class="tiny muted">CUDA usable: {hardware.cudaUsable ? 'yes' : 'no'}</div></div>
            <div><div class="eyebrow">Encoders</div><div class="row tight">{#each hardware.hardwareEncoders as enc}<span class={`pill ${enc.ok ? 'success' : ''}`}>{enc.name} {enc.ok ? 'ok' : 'no'}</span>{/each}</div></div>
            <div class="field">
              <label for="hw-profile">Hardware profile</label>
              <select id="hw-profile" class="select" bind:value={hardwareProfile} onchange={() => patch('hardware', { profile: hardwareProfile })}>
                <option value="auto">Auto ({hardware.recommendedProfile})</option>
                {#each hardware.profiles as p}<option value={p.id}>{p.name}</option>{/each}
              </select>
              <span class="tiny muted">Profiles are guidance, not a speed guarantee. Nothing downloads automatically.</span>
            </div>
            {#each hardware.profiles.filter((p: any) => p.id === hardwareProfile || (hardwareProfile === 'auto' && p.id === hardware.recommendedProfile)) as p}
              <div class="muted-box tiny muted">
                <strong style="color:var(--text)">{p.name}</strong>
                <ul style="margin:8px 0 0;padding-left:16px">{#each p.details as d}<li>{d}</li>{/each}</ul>
              </div>
            {/each}
            <div class="banner"><span>Benchmarks on this machine are available via <span class="mono">scripts/benchmark</span>.</span></div>
          </div>
        {:else}
          <p class="small muted">Detecting hardware…</p>
        {/if}
      </section>

      <section class="card">
        <div class="eyebrow">Downloads</div>
        <h2 style="margin-top:4px">The import lifeline</h2>
        {#if binaries}
          <div class="stack small" style="margin-top:14px">
            <div><span class="eyebrow">FFmpeg</span><div class="mono tiny muted">{binaries.ffmpeg.version || 'missing'}</div></div>
            <div><span class="eyebrow">yt-dlp</span><div class="mono tiny muted">{binaries.ytdlp.version || 'missing'} · {binaries.ytdlp.origin}</div></div>
            <div><span class="eyebrow">JavaScript runtime</span><div class="mono tiny muted">{binaries.jsRuntime.version || 'not installed'}</div></div>
            {#if binaries.notes}<div class="notice warn">{binaries.notes}</div>{/if}
            <div class="field" style="margin-top:10px">
              <label for="cookies-file">YouTube cookies (optional)</label>
              <div class="row">
                <input id="cookies-file" class="input mono" readonly value={cookiesFile || ''} placeholder="No cookies file" />
                <Button size="sm" variant="ghost" onclick={chooseCookies}>Choose…</Button>
                {#if cookiesFile}<Button size="sm" variant="ghost" onclick={clearCookies}>Clear</Button>{/if}
              </div>
              <span class="tiny muted">For videos that ask the downloader to sign in. Export a Netscape-format cookies.txt from a browser where you are signed in. The file stays on this machine and is never sent to the AI provider.</span>
            </div>
          </div>
          <div class="row" style="margin-top:14px">
            <Button size="sm" variant="primary" onclick={updateDownloader} disabled={binariesBusy}>{binariesBusy ? 'Updating…' : 'Update downloader'}</Button>
            <Button size="sm" variant="ghost" onclick={() => (window.location.hash = '#/models')}>Models</Button>
          </div>
        {:else}
          <p class="small muted">Checking binaries…</p>
        {/if}
      </section>

      <section class="card tight">
        <div class="eyebrow">About</div>
        <div class="small" style="margin-top:6px">Clipwright {appState.appInfo?.version || ''}</div>
        <div class="tiny muted mono" style="margin-top:4px">Electron {appState.appInfo?.electron} · Chromium {appState.appInfo?.chrome} · Node {appState.appInfo?.node}</div>
        <div class="row" style="margin-top:12px">
          <Button size="sm" variant="ghost" onclick={() => { setRoute('updates'); void checkForUpdates(true) }}>
            <Icon name="refresh" size={13} /> Check for updates
          </Button>
          {#if updates.data?.status === 'available'}
            <span class="pill gold">v{updates.data.latestVersion} available</span>
          {:else if updates.data?.status === 'current'}
            <span class="tiny muted">Up to date</span>
          {/if}
        </div>
        <p class="tiny muted" style="margin-top:10px">
          For content you own or are authorized to reuse. FFmpeg is bundled as a separate GPL executable; see THIRD_PARTY_LICENSES.md.
        </p>
      </section>
    </div>
  </div>
</div>

{#if providerModal}
  <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (providerModal = null)} role="presentation">
    <div class="modal" role="dialog" aria-modal="true">
      <div><div class="eyebrow">{providerModal.mode === 'add' ? 'New endpoint' : 'Edit provider'}</div><h2>{providerModal.mode === 'add' ? 'Add a provider' : providerModal.profile.name}</h2></div>
      <div class="form-grid">
        <div class="field wide">
          <label for="p-name">Name</label>
          <input id="p-name" class="input" bind:value={providerModal.profile.name} placeholder="My provider" />
        </div>
        <div class="field">
          <label for="p-adapter">Type</label>
          <select id="p-adapter" class="select" bind:value={providerModal.profile.adapter}>
            <option value="groq">Groq</option>
            <option value="openai_compatible">OpenAI-compatible</option>
            <option value="custom">Custom / local</option>
          </select>
        </div>
        <div class="field">
          <label for="p-model">Default model</label>
          <input id="p-model" class="input mono" bind:value={providerModal.profile.defaultModel} placeholder="discover in Settings" />
        </div>
        <div class="field wide">
          <label for="p-url">Base URL</label>
          <input id="p-url" class="input mono" bind:value={providerModal.profile.baseUrl} placeholder="https://api.example.com/v1" />
          <span class="tiny muted">https required except localhost / private LAN. The key is added separately and never saved here.</span>
        </div>
      </div>
      {#if providerError}<div class="notice error">{providerError}</div>{/if}
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (providerModal = null)}>Cancel</Button>
        <Button variant="primary" onclick={saveProvider} disabled={busy || !providerModal.profile.name || !providerModal.profile.baseUrl}>Save provider</Button>
      </div>
    </div>
  </div>
{/if}

{#if keyModal}
  <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (keyModal = null)} role="presentation">
    <div class="modal" role="dialog" aria-modal="true">
      <div><div class="eyebrow">Secure key</div><h2>{keyModal.name}</h2></div>
      <div class="field">
        <label for="provider-key">API key</label>
        <input id="provider-key" class="input mono" type="password" bind:value={keyValue} placeholder="Paste the key" autocomplete="off" />
        <span class="tiny muted">Stored with {secretStatus?.backend || 'the system keyring'} via Electron safeStorage. It is never returned to this window after saving.</span>
      </div>
      {#if secretStatus?.weakBackend}
        <div class="notice warn">
          No secure keyring was detected. By default the key is kept for this session only.
          <label class="check" style="margin-top:8px"><input type="checkbox" bind:checked={allowWeak} /><span>Store it anyway with weak protection</span></label>
        </div>
      {/if}
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (keyModal = null)}>Cancel</Button>
        <Button variant="ghost" onclick={() => { window.clipwright.deleteSecret(keyModal!.id); keyModal = null; loadPeripherals() }}>Remove key</Button>
        <Button variant="primary" onclick={() => saveKey(true)} disabled={busy || !keyValue.trim()}>{busy ? 'Saving…' : 'Save & test'}</Button>
      </div>
    </div>
  </div>
{/if}

{#if deleteTarget}
  <div class="drawer-backdrop" role="presentation">
    <div class="modal" role="alertdialog" aria-modal="true">
      <div class="eyebrow">Remove provider</div>
      <h2>{deleteTarget.name}</h2>
      <p class="soft">This removes the profile and its stored key from this computer. Existing analysis runs and their provider names remain in the project history.</p>
      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (deleteTarget = null)}>Keep it</Button>
        <Button variant="danger" onclick={removeProvider} disabled={busy}>Remove</Button>
      </div>
    </div>
  </div>
{/if}
