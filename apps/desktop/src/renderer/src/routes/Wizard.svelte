<script lang="ts">
  import { appState, saveSettings, refreshBoot, toast } from '$lib/state.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import { bytesLabel } from '$lib/categories'

  let { onFinish, onSkip }: { onFinish: () => void; onSkip: () => void } = $props()

  let step = $state(0)
  let authorization = $state(false)
  let disclosure = $state(false)
  let apiKey = $state('')
  let allowWeak = $state(false)
  let secretStatus = $state<any>(null)
  let testing = $state(false)
  let testResult = $state<any>(null)
  let testError = $state<string | null>(null)
  let selectedModel = $state('')
  let models = $state<string[]>([])
  let transcriptionEngine = $state<'cloud_openai' | 'local_whisper'>('cloud_openai')
  let localModel = $state('small')
  let modelsList = $state<any[]>([])
  let installJob = $state<string | null>(null)
  let outputDir = $state('')
  let saving = $state(false)

  const profile = $derived(appState.providers[0])
  const recommendation = $derived(appState.hardware?.recommendedProfile || 'balanced')
  const steps = ['Welcome', 'AI provider', 'Transcription', 'Storage', 'Ready']

  const installedModels = $derived(modelsList.filter((m) => m.kind === 'whisper' && m.installed).map((m) => m.name))

  $effect(() => {
    if (appState.settings) {
      transcriptionEngine = appState.settings.transcription.engine
      localModel = appState.settings.transcription.localModel
      outputDir = appState.settings.render.outputDir || ''
      disclosure = Boolean(appState.settings.privacy.providerDisclosureAt)
    }
    if (profile && !selectedModel) selectedModel = profile.defaultModel || ''
  })

  $effect(() => {
    if (step === 1) loadSecretStatus()
    if (step === 2) loadModels()
  })

  async function loadSecretStatus() {
    secretStatus = await window.clipwright.secretStatus()
  }

  async function loadModels() {
    try {
      const result = await request('models.list')
      modelsList = result.items || []
    } catch {
      modelsList = []
    }
  }

  async function saveKeyAndTest() {
    if (!profile) {
      toast('error', 'No provider profile exists yet. Re-open the app.')
      return
    }
    testing = true
    testError = null
    testResult = null
    try {
      if (apiKey.trim()) {
        const saved = await window.clipwright.setSecret(profile.id, apiKey, allowWeak)
        await loadSecretStatus()
        if (saved.sessionOnly) {
          toast('info', 'The system keyring is unavailable, so the key is kept for this session only.')
        }
      } else if (!secretStatus?.storedProfiles?.includes(profile.id) && !secretStatus?.sessionProfiles?.includes(profile.id)) {
        throw new Error('Paste an API key first.')
      }
      const result = await request('provider.test', { profileId: profile.id, model: selectedModel || undefined, probe: true })
      testResult = result
      models = (result.models || []).map((m: any) => m.id)
      if (!selectedModel) selectedModel = result.chosenModel || ''
      if (selectedModel) {
        await request('provider.save', {
          profile: { ...profile, defaultModel: selectedModel, capabilities: result.capabilities }
        })
      }
      await saveSettings('providers', { defaultProfileId: profile.id })
      await refreshBoot()
      toast('success', `Connected to ${profile.name}${result.latencyMs ? ` in ${Math.round(result.latencyMs)} ms` : ''}.`)
    } catch (error) {
      testError = errorText(error)
    } finally {
      testing = false
    }
  }

  async function saveModelChoice() {
    if (!profile) return
    await request('provider.save', { profile: { ...profile, defaultModel: selectedModel } })
    await refreshBoot()
  }

  async function installWhisper() {
    try {
      const job = await request('models.download', { kind: 'whisper', name: localModel })
      installJob = job.jobId
      toast('info', `Downloading the ${localModel} model…`)
    } catch (error) {
      toast('error', errorText(error))
    }
  }

  async function persistStep() {
    if (step === 1 && profile && selectedModel) {
      await request('provider.save', { profile: { ...profile, defaultModel: selectedModel } }).catch(() => null)
      await saveSettings('providers', { defaultProfileId: profile.id })
    }
    if (step === 2) {
      await saveSettings('transcription', {
        engine: transcriptionEngine,
        localModel,
        providerProfileId: profile?.id
      })
    }
    if (step === 3 && outputDir) {
      await saveSettings('render', { outputDir })
    }
  }

  async function next() {
    saving = true
    try {
      await persistStep()
      if (step < steps.length - 1) step += 1
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      saving = false
    }
  }

  async function finish() {
    saving = true
    try {
      await persistStep()
      await saveSettings('privacy', {
        authorizationAcknowledgedAt: authorization ? new Date().toISOString() : appState.settings?.privacy.authorizationAcknowledgedAt,
        providerDisclosureAt: disclosure ? new Date().toISOString() : appState.settings?.privacy.providerDisclosureAt
      })
      await saveSettings('wizard', { completed: true })
      await refreshBoot()
      onFinish()
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      saving = false
    }
  }

  async function chooseFolder() {
    const folder = await window.clipwright.chooseFolder()
    if (folder) outputDir = folder.path
  }

  async function checkInstallJob() {
    if (!installJob) return
    const job = await request('jobs.get', { jobId: installJob })
    if (job.job.state === 'succeeded') {
      installJob = null
      await loadModels()
      toast('success', 'Model installed.')
    }
  }

  $effect(() => {
    if (installJob) {
      const timer = setInterval(checkInstallJob, 1200)
      return () => clearInterval(timer)
    }
  })
</script>

<div class="wizard-shell">
  <aside class="wizard-art">
    <div class="row" style="gap:12px">
      <div class="brand-mark">C</div>
      <div>
        <div class="brand-name">Clipwright</div>
        <div class="brand-sub">Short-form editor</div>
      </div>
    </div>
    <div style="max-width:520px;position:relative;z-index:1">
      <h1>Find the moments first.</h1>
      <p class="soft" style="margin-top:16px;max-width:420px">
        Clipwright reads the whole conversation, proposes the moments worth keeping, and gives you a
        calm place to turn them into vertical Shorts. Nothing leaves this computer until you choose a provider.
      </p>
      <div class="filmstrip" style="margin-top:32px;width:340px"></div>
    </div>
    <div class="mono tiny muted">BYOK · YOUR KEY, YOUR PROVIDER · NO ACCOUNTS</div>
  </aside>

  <section class="wizard-main">
    <div class="steps" aria-label={`Step ${step + 1} of ${steps.length}`}>
      {#each steps as _s, i}
        <div class={`step-dot ${i <= step ? 'active' : ''}`}></div>
      {/each}
    </div>
    <div class="spread">
      <div>
        <div class="eyebrow">Setup · Step {step + 1} of {steps.length}</div>
        <h2 style="margin-top:6px">{steps[step]}</h2>
      </div>
      <button class="link tiny" onclick={onSkip}>Skip setup</button>
    </div>

    {#if step === 0}
      <div class="stack">
        <p class="soft">
          Clipwright is for content you own or are authorized to reuse. A video being reachable online does
          not mean it is yours to download or republish.
        </p>
        <label class="check">
          <input type="checkbox" bind:checked={authorization} />
          <span>I understand and will only analyze content I own or have permission to use.</span>
        </label>
        <p class="tiny muted">
          Local files stay on this computer. For online imports, only the audio needed for a transcript and the
          short video sections you select are fetched. The app shows an acknowledgement again when you first import a link.
        </p>
      </div>
    {:else if step === 1}
      <div class="stack">
        <p class="soft">
          Clipwright uses your own key with any OpenAI-compatible provider. Groq is pre-filled because it is fast
          and has a free tier. The key is stored in the operating system's secure storage, never in the project database.
        </p>
        {#if !profile}
          <div class="notice error">No provider profile was created. Re-open the app.</div>
        {:else}
          <div class="muted-box">
            <div class="spread">
              <div>
                <div class="eyebrow">Provider</div>
                <h3 style="margin-top:4px">{profile.name}</h3>
                <div class="tiny muted mono">{profile.baseUrl}</div>
              </div>
              <span class="pill gold">Default</span>
            </div>
          </div>
          <div class="field">
            <label for="groq-key">API key</label>
            <input id="groq-key" class="input mono" type="password" bind:value={apiKey} placeholder="gsk_…" autocomplete="off" />
            <div class="row tiny muted">
              <span>Create a key at console.groq.com/keys.</span>
              {#if secretStatus?.storedProfiles?.includes(profile.id)}<span class="pill success">stored</span>{/if}
              {#if secretStatus?.weakBackend}
                <label class="check" style="margin-left:auto">
                  <input type="checkbox" bind:checked={allowWeak} />
                  <span>Store with weak protection</span>
                </label>
              {/if}
            </div>
            {#if secretStatus?.weakBackend}
              <div class="notice warn">
                This system has no keyring, so keys are kept for this session only unless you tick the weak-protection box.
              </div>
            {/if}
          </div>
          <div class="row">
            <Button variant="primary" disabled={testing || (!apiKey && !secretStatus?.storedProfiles?.includes(profile.id))} onclick={saveKeyAndTest}>
              {#if testing}<Icon name="loader" size={15} /> Testing…{:else}<Icon name="key" size={15} /> Save & test connection{/if}
            </Button>
            {#if profile.envKeyAvailable}<span class="pill success">GROQ_API_KEY found in environment</span>{/if}
          </div>
          {#if testError}<div class="notice error">{testError}</div>{/if}
          {#if testResult}
            <div class="notice gold">
              Connected in {Math.round(testResult.latencyMs)} ms · {testResult.modelCount} models · structured output:
              {testResult.capabilities?.supportsJsonSchemaStrict || testResult.capabilities?.supports_json_schema_strict ? 'strict' : 'best effort'}
            </div>
            <div class="form-grid">
              <div class="field wide">
                <label for="model">Model for clip finding</label>
                <select id="model" class="select" bind:value={selectedModel} onchange={saveModelChoice}>
                  {#if selectedModel}<option value={selectedModel}>{selectedModel}</option>{/if}
                  {#each models.filter((m) => m !== selectedModel) as model}
                    <option value={model}>{model}</option>
                  {/each}
                </select>
                <span class="tiny muted">Structured output support is probed per model; the app falls back safely if a model lacks it.</span>
              </div>
            </div>
          {/if}
        {/if}
        <label class="check">
          <input type="checkbox" bind:checked={disclosure} />
          <span>
            I understand that transcript windows, clip titles and metadata are sent to this provider during analysis.
            Audio is sent only if I choose cloud transcription. Never whole videos.
          </span>
        </label>
        <button class="link tiny" onclick={() => (step = 2)}>Skip for now — add a provider later</button>
      </div>
    {:else if step === 2}
      <div class="stack">
        <p class="soft">
          Clipwright recommends {recommendation === 'low' ? 'cloud transcription for speed on this machine' : 'local transcription for privacy on this machine'}.
          You can change this at any time; nothing switches silently.
        </p>
        <div class="choice-grid">
          <button class={`choice ${transcriptionEngine === 'cloud_openai' ? 'active' : ''}`} onclick={() => (transcriptionEngine = 'cloud_openai')}>
            <h3><Icon name="cloud" size={18} /> Cloud · fast</h3>
            <p>Audio chunks (16 kHz mono, up to 10 minutes) are sent to your speech provider. Best on weak CPUs.</p>
            <span class="pill gold">Recommended here</span>
          </button>
          <button class={`choice ${transcriptionEngine === 'local_whisper' ? 'active' : ''}`} onclick={() => (transcriptionEngine = 'local_whisper')}>
            <h3><Icon name="mic" size={18} /> Local · private</h3>
            <p>Runs Whisper on this computer. No audio leaves it. Slower, and needs a downloaded model.</p>
            <span class={`pill ${installedModels.includes(localModel) ? 'success' : 'warn'}`}>
              {installedModels.includes(localModel) ? 'Installed' : 'Needs download'}
            </span>
          </button>
        </div>
        {#if transcriptionEngine === 'local_whisper'}
          <div class="form-grid">
            <div class="field">
              <label for="local-model">Local model</label>
              <select id="local-model" class="select" bind:value={localModel}>
                {#each modelsList.filter((m) => m.kind === 'whisper') as model}
                  <option value={model.name}>{model.label} · {model.downloadMb} MB</option>
                {/each}
              </select>
            </div>
            <div class="field" style="align-content:end">
              {#if installedModels.includes(localModel)}
                <span class="pill success" style="align-self:start">Ready to transcribe</span>
              {:else}
                <Button variant="ghost" onclick={installWhisper} disabled={Boolean(installJob)}>
                  <Icon name="download" size={14} /> Download model
                </Button>
              {/if}
            </div>
          </div>
          {#if installJob}
            <div class="notice">Downloading… you can keep going; installs continue in the background.</div>
          {/if}
        {/if}
        <label class="check">
          <input type="checkbox" bind:checked={disclosure} />
          <span>I understand what gets sent to my chosen provider.</span>
        </label>
      </div>
    {:else if step === 3}
      <div class="stack">
        <div class="muted-box">
          <div class="eyebrow">Application data</div>
          <div class="small mono" style="margin-top:6px">{appState.settings?.dataDir || appState.appInfo?.userData}</div>
          <p class="tiny muted" style="margin-top:8px">
            Projects, transcripts and cached sections live here. Whisper models live under Models.
            {appState.hardware ? `${bytesLabel(appState.hardware.freeDiskBytes)} free on this volume.` : ''}
          </p>
        </div>
        <div class="field">
          <label for="export-folder">Default export folder</label>
          <div class="row">
            <input id="export-folder" class="input mono" readonly value={outputDir} />
            <Button variant="ghost" onclick={chooseFolder}><Icon name="folder" size={14} /> Choose</Button>
          </div>
        </div>
        <div class="notice">
          Exports are H.264 High, yuv420p, 1080×1920, AAC 192 kbps. A render is only marked successful after ffprobe validates it.
        </div>
      </div>
    {:else}
      <div class="stack">
        <div class="muted-box">
          <div class="spread">
            <div>
              <div class="eyebrow">You're set</div>
              <h3 style="margin-top:4px">Ready to find moments</h3>
            </div>
            <Icon name="spark" size={26} />
          </div>
          <hr class="hairline" style="margin:16px 0" />
          <div class="row tiny muted">
            <span class="pill gold">{profile?.name || 'Provider not configured'}</span>
            <span class="pill">{transcriptionEngine === 'local_whisper' ? 'Local transcription' : 'Cloud transcription'}</span>
            <span class="pill">{recommendation} hardware</span>
          </div>
        </div>
        <p class="soft">
          Every step can be changed in Settings. If something needs an API key later, the app will say exactly what is missing.
        </p>
      </div>
    {/if}

    <div class="row" style="margin-top:auto;justify-content:space-between">
      <button class="link tiny muted" onclick={() => (step = Math.max(0, step - 1))} disabled={step === 0}>Back</button>
      <div class="row">
        {#if step === 0 && !authorization}
          <span class="tiny muted">Acknowledge to continue, or skip setup.</span>
        {/if}
        {#if step < steps.length - 1}
          <Button variant="primary" disabled={saving || (step === 0 && !authorization)} onclick={next}>Continue</Button>
        {:else}
          <Button variant="primary" disabled={saving} onclick={finish}>{saving ? 'Saving…' : 'Enter Clipwright'}</Button>
        {/if}
      </div>
    </div>
  </section>
</div>
