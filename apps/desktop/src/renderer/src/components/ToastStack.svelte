<script lang="ts">
  import { appState } from '$lib/state.svelte'
</script>

<div class="toast-stack" aria-live="polite">
  {#each appState.toasts as toast (toast.id)}
    <div class={`toast ${toast.kind}`}>
      <div>{toast.message}</div>
      {#if toast.details}<details><summary>Details</summary>{toast.details}</details>{/if}
    </div>
  {/each}
</div>
