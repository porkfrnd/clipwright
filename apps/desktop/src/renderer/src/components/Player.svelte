<script lang="ts">
  import Icon from './Icon.svelte'
  import { timecode } from '$lib/categories'

  let {
    src = null,
    startS = 0,
    endS = null,
    layout = 'fill',
    zoom = 1,
    onTime,
    label = 'Preview'
  }: {
    src?: string | null
    startS?: number
    endS?: number | null
    layout?: 'fill' | 'blur' | 'manual' | string
    zoom?: number
    onTime?: (time: number) => void
    label?: string
  } = $props()

  let video: HTMLVideoElement | undefined = $state()
  let backdrop: HTMLVideoElement | undefined = $state()
  let playing = $state(false)
  let muted = $state(false)
  let current = $state(0)
  let duration = $state(0)
  let failed = $state(false)

  export function seek(time: number) {
    if (!video) return
    video.currentTime = Math.max(0, time)
    if (backdrop && backdrop.readyState >= 1) backdrop.currentTime = video.currentTime
    current = video.currentTime
    onTime?.(current)
  }

  export function play() {
    video?.play().catch(() => (failed = true))
  }

  export function pause() {
    video?.pause()
  }

  function loaded() {
    if (!video) return
    duration = video.duration || 0
    video.currentTime = Math.max(0, Math.min(startS, duration || startS))
    if (backdrop && backdrop.readyState >= 1) backdrop.currentTime = video.currentTime
    current = video.currentTime
  }

  function tick() {
    if (!video) return
    current = video.currentTime
    if (backdrop && Math.abs(backdrop.currentTime - video.currentTime) > 0.2) {
      backdrop.currentTime = video.currentTime
    }
    onTime?.(current)
    if (endS != null && current >= endS - 0.03 && !video.paused) {
      video.pause()
    }
  }

  function toggle() {
    if (!video) return
    if (video.paused) {
      if (endS != null && current >= endS - 0.1) {
        video.currentTime = startS
        if (backdrop) backdrop.currentTime = startS
      }
      video.play().catch(() => (failed = true))
      backdrop?.play().catch(() => undefined)
    } else {
      video.pause()
      backdrop?.pause()
    }
  }

  $effect(() => {
    if (src && video && video.src !== src) {
      failed = false
      video.load()
    }
  })
</script>

<div class={`player-frame layout-${layout}`}>
  {#if src}
    {#if layout === 'blur'}
      <video
        bind:this={backdrop}
        class="tile-bg"
        {src}
        playsinline
        preload="auto"
        muted
        tabindex="-1"
        aria-hidden="true"
        onloadedmetadata={() => { if (backdrop && video) backdrop.currentTime = video.currentTime }}
      ></video>
    {/if}
    <video
      bind:this={video}
      class="tile-fg"
      {src}
      playsinline
      preload="metadata"
      onloadedmetadata={loaded}
      ontimeupdate={tick}
      onplay={() => (playing = true)}
      onpause={() => (playing = false)}
      onerror={() => (failed = true)}
      muted={muted}
      style={layout === 'manual' ? `transform:scale(${zoom || 1})` : ''}
    ></video>
  {:else}
    <div class="player-empty">
      <div>
        <Icon name="film" size={38} />
        <div style="margin-top:12px">{label} appears here.<br />Pick a moment to load the video.</div>
      </div>
    </div>
  {/if}
  {#if failed}
    <div class="player-empty">This video could not be loaded. For an online source, fetch a preview first.</div>
  {/if}
  {#if src && !failed}
    <div
      style="position:absolute;left:10px;right:10px;bottom:10px;display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:999px;background:rgba(6,5,10,.72);backdrop-filter:blur(10px)"
    >
      <button class="icon-btn" style="width:32px;height:32px;border:0" onclick={toggle} title={playing ? 'Pause' : 'Play'}>
        <Icon name={playing ? 'pause' : 'play'} size={15} />
      </button>
      <span class="mono tiny" style="color:#fff">{timecode(current, true)}</span>
      <div style="flex:1;height:3px;background:rgba(255,255,255,.18);border-radius:99px;overflow:hidden">
        <div style={`height:100%;width:${duration ? (current / duration) * 100 : 0}%;background:var(--accent)`}></div>
      </div>
      <button class="icon-btn" style="width:30px;height:30px;border:0" onclick={() => (muted = !muted)} title={muted ? 'Unmute' : 'Mute'}>
        <Icon name="volume" size={14} />
      </button>
    </div>
  {/if}
</div>
