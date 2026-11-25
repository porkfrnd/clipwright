<script lang="ts">
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'

  let { fatal, onReload, onRestart }: { fatal: { reason: string; logTail: string[] }; onReload: () => void; onRestart: () => void } = $props()
  let copied = $state(false)
  const log = $derived((fatal.logTail || []).join('\n').slice(-12000))

  async function copyLog() {
    await navigator.clipboard.writeText(log)
    copied = true
    setTimeout(() => (copied = false), 1800)
  }
</script>

<div class="recovery">
  <div class="recovery-card">
    <div class="row">
      <div class="brand-mark">C</div>
      <div>
        <div class="eyebrow">Clipwright</div>
        <h2 style="font-size:44px">The engine needs a restart</h2>
      </div>
    </div>
    <div class="card raised">
      <h3>What happened</h3>
      <p class="soft" style="margin-top:8px">{fatal.reason}</p>
      <p class="small muted" style="margin-top:12px">
        Your projects, transcripts and edit settings are saved. Nothing was deleted. The app stopped
        restarting the engine automatically to avoid a crash loop.
      </p>
      <div class="row" style="margin-top:18px">
        <Button variant="primary" onclick={onRestart}><Icon name="refresh" size={15} /> Restart engine</Button>
        <Button variant="ghost" onclick={onReload}>Reload window</Button>
        <Button variant="ghost" onclick={copyLog}><Icon name="text" size={14} /> {copied ? 'Copied' : 'Copy log for support'}</Button>
      </div>
    </div>
    <details class="card quiet">
      <summary class="small muted" style="cursor:pointer">Engine log tail</summary>
      <pre class="log-tail" style="margin-top:12px">{log || 'No log lines were captured.'}</pre>
    </details>
  </div>
</div>
