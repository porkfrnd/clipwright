<script lang="ts">
  import { request, errorText } from '$lib/api'
  import Button from '$components/Button.svelte'
  import Icon from '$components/Icon.svelte'

  let {
    sourceId,
    transcriptId,
    profiles = [],
    defaultProfileId = null,
    defaultModel = "",
    onAdopt
  }: {
    sourceId: string
    transcriptId: string
    profiles: any[]
    defaultProfileId: string | null
    defaultModel: string
    onAdopt: (profileId: string, model: string) => void
  } = $props()

  let open = $state(false)
  let profileA = $state<string | null>(null)
  let profileB = $state<string | null>(null)
  let modelA = $state("")
  let modelB = $state("")
  let modelsA = $state<any[]>([])
  let modelsB = $state<any[]>([])
  let loadingA = $state(false)
  let loadingB = $state(false)
  let busy = $state(false)
  let error = $state<string | null>(null)
  let result = $state<any>(null)

  const providerA = $derived(profiles.find((p) => p.id === profileA) || null)
  const providerB = $derived(profiles.find((p) => p.id === profileB) || null)
  const canRun = $derived(Boolean(profileA && profileB && modelA.trim() && modelB.trim() && !busy))

  async function loadModels(profileId: string | null, side: "a" | "b") {
    if (!profileId) return
    if (side === "a") loadingA = true
    else loadingB = true
    try {
      const data = await request<any>('provider.list_models', { profileId })
      const list = data.models || []
      if (side === "a") {
        modelsA = list
        if (!modelA) modelA = list[0]?.id || ""
      } else {
        modelsB = list
        if (!modelB) modelB = list[0]?.id || ""
      }
    } catch {
      // A provider can be offline or missing a key. Keep the typed model.
    } finally {
      if (side === "a") loadingA = false
      else loadingB = false
    }
  }

  async function show() {
    open = true
    profileA = profileA || defaultProfileId
    profileB = profileB || profiles.find((p) => p.id !== defaultProfileId)?.id || defaultProfileId
    if (!modelA) modelA = defaultModel || profiles.find((p) => p.id === profileA)?.defaultModel || ""
    if (!modelB) modelB = profiles.find((p) => p.id === profileB)?.defaultModel || ""
    if (profileA) void loadModels(profileA, "a")
    if (profileB) void loadModels(profileB, "b")
  }

  function pickProfile(side: "a" | "b", value: string) {
    if (side === "a") {
      profileA = value
      modelA = profiles.find((p) => p.id === value)?.defaultModel || ""
      modelsA = []
      void loadModels(value, "a")
    } else {
      profileB = value
      modelB = profiles.find((p) => p.id === value)?.defaultModel || ""
      modelsB = []
      void loadModels(value, "b")
    }
  }

  async function run() {
    if (!canRun) return
    busy = true
    error = null
    result = null
    try {
      result = await request('analysis.compare', {
        sourceId,
        transcriptId,
        profileAId: profileA,
        modelA: modelA.trim(),
        profileBId: profileB,
        modelB: modelB.trim()
      })
    } catch (err) {
      error = errorText(err)
    } finally {
      busy = false
    }
  }
</script>

<button class="compare-link" onclick={show}><Icon name="split" size={13} /> Compare providers</button>

{#if open}
  <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (open = false)} role="presentation">
    <div class="modal provider-modal" role="dialog" aria-modal="true" aria-labelledby="provider-compare-title">
      <div class="spread">
        <div><div class="eyebrow">Dry run</div><h2 id="provider-compare-title">Compare providers</h2></div>
        <button class="icon-btn" onclick={() => (open = false)} aria-label="Close provider comparison"><Icon name="x" size={16} /></button>
      </div>
      <p class="small muted">Two models read the same cached transcript. This does not re-transcribe, and nothing is saved until you explicitly analyze with one of them.</p>

      <div class="compare-setup">
        <div class="compare-side">
          <span class="eyebrow">Provider A</span>
          <select class="select" value={profileA || ""} onchange={(e) => pickProfile("a", (e.currentTarget as HTMLSelectElement).value)} aria-label="Provider A">
            {#each profiles as profile}<option value={profile.id}>{profile.name}</option>{/each}
          </select>
          <input class="input mono" bind:value={modelA} list="models-a" placeholder={loadingA ? "Loading models…" : "Model id"} aria-label="Model A" />
          <datalist id="models-a">{#each modelsA as model}<option value={model.id}>{model.id}</option>{/each}</datalist>
        </div>
        <span class="compare-vs">vs</span>
        <div class="compare-side">
          <span class="eyebrow">Provider B</span>
          <select class="select" value={profileB || ""} onchange={(e) => pickProfile("b", (e.currentTarget as HTMLSelectElement).value)} aria-label="Provider B">
            {#each profiles as profile}<option value={profile.id}>{profile.name}</option>{/each}
          </select>
          <input class="input mono" bind:value={modelB} list="models-b" placeholder={loadingB ? "Loading models…" : "Model id"} aria-label="Model B" />
          <datalist id="models-b">{#each modelsB as model}<option value={model.id}>{model.id}</option>{/each}</datalist>
        </div>
      </div>

      <div class="row" style="justify-content:flex-end">
        <Button variant="ghost" onclick={() => (open = false)}>Cancel</Button>
        <Button variant="primary" onclick={run} disabled={!canRun}>{busy ? "Reading with both…" : "Run comparison"}</Button>
      </div>
      {#if error}<div class="notice error">{error}</div>{/if}

      {#if result}
        <div class="compare-results">
          {#each [result.a, result.b] as side, index}
            <div class={`compare-result ${result.recommended === side.providerId && result.recommended ? "recommended" : ""}`}>
              <div class="spread"><span class="eyebrow">Provider {index === 0 ? "A" : "B"}</span>{#if result.recommended === side.providerId}<span class="pill gold">Recommended</span>{/if}</div>
              <h3>{side.provider}</h3>
              <div class="mono tiny muted">{side.model}</div>
              {#if side.error}
                <div class="notice error tiny">{side.error}</div>
              {:else}
                <div class="compare-metrics">
                  <div><strong>{side.candidateCount}</strong><span>candidates</span></div>
                  <div><strong>{side.avgFit}</strong><span>mean fit</span></div>
                  <div><strong>{side.avgDurationS}s</strong><span>avg length</span></div>
                </div>
                <div class="tiny muted">{side.minDurationS}–{side.maxDurationS}s · {side.tokens.toLocaleString()} tokens</div>
                <div class="compare-cuts">
                  {#each side.candidates.slice(0, 3) as candidate}
                    <div class="tiny"><span class="mono">{candidate.startS != null ? Math.round(candidate.startS) + "s" : "—"}</span> {candidate.title}</div>
                  {/each}
                </div>
                <Button size="sm" variant="ghost" onclick={() => { onAdopt(side.providerId, side.model); open = false }}>Analyze with this one</Button>
              {/if}
            </div>
          {/each}
        </div>
        <div class="notice tiny">{result.recommendation} {result.disclosure}</div>
      {/if}
    </div>
  </div>
{/if}
