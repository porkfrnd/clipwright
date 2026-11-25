<script lang="ts">
  const PRESETS: Record<string, { label: string; top: number; bottom: number; right: number; note: string }> = {
    tiktok: {
      label: 'TikTok',
      top: 10,
      bottom: 18,
      right: 14,
      note: 'Keep captions above the lower toolbar and left of the action rail.'
    },
    reels: {
      label: 'Reels',
      top: 12,
      bottom: 20,
      right: 15,
      note: 'Reels reserves more room for the caption block and profile actions.'
    },
    shorts: {
      label: 'Shorts',
      top: 8,
      bottom: 22,
      right: 13,
      note: 'Shorts places the title and subscribe control over the lower frame.'
    }
  }

  let {
    platform = 'none',
    visible = false
  }: {
    platform?: string
    visible?: boolean
  } = $props()

  const preset = $derived(PRESETS[platform] || null)
</script>

{#if visible && preset}
  <div class="safe-zone" aria-label={`${preset.label} safe-zone guide`}>
    <div class="safe-band safe-top" style={`height:${preset.top}%`}><span>UI · top {preset.top}%</span></div>
    <div class="safe-band safe-right" style={`width:${preset.right}%`}><span>actions</span></div>
    <div class="safe-band safe-bottom" style={`height:${preset.bottom}%`}><span>UI · bottom {preset.bottom}%</span></div>
    <div class="safe-frame" style={`inset:${preset.top}% ${preset.right}% ${preset.bottom}% 0`}></div>
  </div>
{/if}
