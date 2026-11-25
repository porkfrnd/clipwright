<script lang="ts">
  import { onMount } from 'svelte'
  import { appState, toast } from '$lib/state.svelte'
  import {
    checkForUpdates,
    startUpdateChecks,
    updateIsAvailable,
    updates
  } from '$lib/updates.svelte'
  import { chooseAsset, UPDATE_RELEASES_URL } from '$shared/updates'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'

  type NoteBlock = { kind: 'heading' | 'text' | 'item'; text: string }

  const currentVersion = $derived(updates.data?.currentVersion || appState.appInfo?.version || '0.0.0')
  const release = $derived(updates.data)
  const platform = $derived(appState.appInfo?.platform || 'linux')
  const arch = $derived(appState.appInfo?.arch || 'x64')
  const platformLabel = $derived(platform === 'win32' ? 'Windows' : platform === 'darwin' ? 'macOS' : 'Linux')
  const asset = $derived(chooseAsset(release?.assets, platform, arch))
  const notes = $derived(parseNotes(release?.releaseNotes))
  const waiting = $derived(updates.checking)

  onMount(() => {
    startUpdateChecks()
    if (!updates.data || updates.data.status === 'idle') void checkForUpdates(false)
  })

  function cleanInline(value: string): string {
    return value
      .replace(/\!\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/__(.+?)__/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/^>\s?/, '')
      .trim()
  }

  function parseNotes(raw?: string): NoteBlock[] {
    if (!raw) return []
    const blocks: NoteBlock[] = []
    for (const line of raw.replace(/\r/g, '').split('\n')) {
      const value = line.trim()
      if (!value || /^[-*_]{3,}$/.test(value)) continue
      if (/^#{1,6}\s/.test(value)) {
        const heading = cleanInline(value.replace(/^#{1,6}\s+/, ''))
        // GitHub's generated release notes often open with the same heading the page already shows.
        if (!blocks.length && /^what(?:'s| is)? changed$/i.test(heading)) continue
        blocks.push({ kind: 'heading', text: heading })
      } else if (/^[-*+]\s+/.test(value)) {
        blocks.push({ kind: 'item', text: cleanInline(value.replace(/^[-*+]\s+/, '')) })
      } else if (/^\d+[.)]\s+/.test(value)) {
        blocks.push({ kind: 'item', text: cleanInline(value.replace(/^\d+[.)]\s+/, '')) })
      } else {
        blocks.push({ kind: 'text', text: cleanInline(value) })
      }
      if (blocks.length >= 80) break
    }
    return blocks
  }

  function dateLabel(iso?: string): string {
    if (!iso) return ''
    const date = new Date(iso)
    if (Number.isNaN(date.getTime())) return ''
    return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  }

  function checkedLabel(iso?: string): string {
    if (!iso) return 'Not checked in this session'
    const date = new Date(iso)
    if (Number.isNaN(date.getTime())) return 'Not checked in this session'
    return `Checked ${date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
  }

  async function openUrl(url?: string): Promise<void> {
    if (!url) return
    try {
      const opened = await window.clipwright.openExternal(url)
      if (!opened) toast('error', 'The release page could not be opened.')
    } catch {
      toast('error', 'The release page could not be opened.')
    }
  }

  function sizeLabel(bytes: number): string {
    if (!bytes) return ''
    const mb = bytes / (1024 * 1024)
    return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`
  }
</script>

<div class="page updates-page">
  <header class="page-head updates-head">
    <div>
      <div class="eyebrow">Application</div>
      <h1>Updates</h1>
      <p class="lead">Clipwright checks the public GitHub release feed when it opens. No account, no telemetry, and nothing about your projects leaves this machine.</p>
    </div>
    <div class="updates-head-meta">
      <span class="mono tiny">Installed v{currentVersion}</span>
      <Button size="sm" variant="ghost" onclick={() => checkForUpdates(true)} disabled={updates.checking}>
        <Icon name="refresh" size={14} /> {updates.checking ? 'Checking…' : 'Check again'}
      </Button>
    </div>
  </header>

  <div class="updates-grid">
    <section class="release-sheet" aria-live="polite">
      <div class="release-ledger">
        <div class="release-cell">
          <span class="eyebrow">Installed</span>
          <strong class="release-version">v{currentVersion}</strong>
        </div>
        <div class="release-rail" aria-hidden="true"><span></span><Icon name="chevron" size={12} /></div>
        <div class={`release-cell ${updateIsAvailable() ? 'is-new' : ''}`}>
          <span class="eyebrow">Latest on GitHub</span>
          <strong class="release-version">{release?.latestVersion ? `v${release.latestVersion}` : '—'}</strong>
        </div>
      </div>

      {#if waiting}
        <div class="release-wait">
          <Icon name="loader" size={22} />
          <div>
            <h2>Asking GitHub for the latest release…</h2>
            <p>This takes a moment. The rest of the app keeps working.</p>
          </div>
        </div>
      {:else if release?.status === 'error'}
        <div class="release-error">
          <div class="notice error">
            <strong>Could not check for updates.</strong>
            <span>{release.error}</span>
          </div>
          <div class="row" style="margin-top:14px">
            <Button size="sm" variant="primary" onclick={() => checkForUpdates(true)} disabled={updates.checking}>
              <Icon name="refresh" size={14} /> Try again
            </Button>
            <Button size="sm" variant="ghost" onclick={() => openUrl(UPDATE_RELEASES_URL)}>Open releases on GitHub</Button>
          </div>
          <p class="tiny muted" style="margin-top:12px">A failed check never blocks the app and never retries on a loop.</p>
        </div>
      {:else if !release || release.status === 'idle'}
        <div class="release-wait">
          <Icon name="refresh" size={20} />
          <div>
            <h2>Ready when you are.</h2>
            <p>No update check has run in this session yet.</p>
          </div>
        </div>
        <div class="release-actions">
          <Button variant="primary" onclick={() => checkForUpdates(true)} disabled={updates.checking}>
            <Icon name="refresh" size={14} /> Check for updates
          </Button>
          <Button variant="ghost" onclick={() => openUrl(UPDATE_RELEASES_URL)}>Open releases on GitHub</Button>
        </div>
      {:else if updateIsAvailable()}
        <div class="release-copy">
          <div class="release-kicker"><span class="dot"></span> New release</div>
          <h2 class="release-title">{release?.releaseName || `Clipwright ${release?.latestVersion}`}</h2>
          <p class="release-when">
            {#if release?.publishedAt}Published {dateLabel(release.publishedAt)}{/if}
            {#if asset} · {asset.name}{/if}
          </p>
          <div class="release-actions">
            <Button variant="primary" onclick={() => openUrl(asset?.url || release?.releaseUrl)}>
              <Icon name="download" size={15} />
              {asset ? `Download for ${platformLabel}` : 'Open release page'}
            </Button>
            <Button variant="ghost" onclick={() => openUrl(release?.releaseUrl)}>
              Release notes <Icon name="external" size={13} />
            </Button>
          </div>
          {#if asset}
            <div class="asset-meta tiny muted">
              <span class="mono">{asset.name}</span>
              {#if asset.size}<span>· {sizeLabel(asset.size)}</span>{/if}
            </div>
          {/if}
        </div>

        {#if notes.length}
          <div class="release-notes">
            <div class="section-title"><h2>What changed</h2><div class="rule"></div></div>
            <div class="release-notes-scroll">
              {#each notes as block}
                {#if block.kind === 'heading'}
                  <h3>{block.text}</h3>
                {:else if block.kind === 'item'}
                  <p class="note-item">{block.text}</p>
                {:else}
                  <p>{block.text}</p>
                {/if}
              {/each}
            </div>
          </div>
        {/if}

        {#if release?.assets?.length}
          <details class="release-assets">
            <summary>All release files ({release.assets.length})</summary>
            <div class="asset-list">
              {#each release.assets as item}
                <button class="asset-row" onclick={() => openUrl(item.url)}>
                  <span class="grow"><span class="mono tiny">{item.name}</span></span>
                  <span class="tiny muted">{sizeLabel(item.size)}</span>
                  <Icon name="external" size={13} />
                </button>
              {/each}
            </div>
          </details>
        {/if}
      {:else}
        <div class="release-current">
          <div class="release-current-mark"><Icon name="check" size={24} /></div>
          <div>
            <h2 class="release-title">You're on the latest cut.</h2>
            <p>Clipwright {currentVersion} is the newest published release.</p>
            <p class="tiny muted">{checkedLabel(release?.checkedAt)}</p>
          </div>
        </div>
        <div class="release-actions">
          <Button variant="ghost" onclick={() => checkForUpdates(true)} disabled={updates.checking}>
            <Icon name="refresh" size={14} /> Check again
          </Button>
          <Button variant="ghost" onclick={() => openUrl(release?.releaseUrl || UPDATE_RELEASES_URL)}>
            Release notes <Icon name="external" size={13} />
          </Button>
        </div>
      {/if}
    </section>

    <aside class="stack updates-aside">
      <section class="card tight">
        <div class="eyebrow">The check</div>
        <h3>Quiet by default</h3>
        <p class="small muted">One request when the app opens. Manual checks are cached for ten minutes; nothing polls in the background.</p>
        <div class="rule" style="margin:14px 0"></div>
        <dl class="update-facts">
          <div><dt>Request</dt><dd>Public GitHub Releases API</dd></div>
          <div><dt>Sends</dt><dd>App name and version only</dd></div>
          <div><dt>Needs</dt><dd>No account, key, or token</dd></div>
          <div><dt>On failure</dt><dd>Stays quiet; you can retry here</dd></div>
        </dl>
      </section>

      <section class="card tight">
        <div class="eyebrow">Release feed</div>
        <button class="link small" onclick={() => openUrl(UPDATE_RELEASES_URL)}>github.com/porkfrnd/clipwright</button>
        <p class="tiny muted" style="margin-top:8px">Downloads open in your browser. Clipwright never installs an update without asking.</p>
      </section>

      <section class="card tight">
        <div class="eyebrow">This build</div>
        <div class="tiny muted mono" style="margin-top:6px">v{currentVersion} · Electron {appState.appInfo?.electron || '—'}</div>
        <div class="tiny muted" style="margin-top:4px">{platformLabel} · {arch}</div>
      </section>
    </aside>
  </div>
</div>
