<script lang="ts">
  import { appState, setRoute, refreshBoot, toast } from '$lib/state.svelte'
  import { request, errorText } from '$lib/api'
  import Icon from '$components/Icon.svelte'
  import Button from '$components/Button.svelte'
  import type { Project } from '$shared/types'

  let deleting = $state<Project | null>(null)
  let newName = $state('')
  let busy = $state(false)

  async function create() {
    const name = newName.trim()
    if (!name) return
    busy = true
    try {
      const result = await request<{ project: Project }>('project.create', { name })
      appState.projects = [result.project, ...appState.projects]
      newName = ''
      setRoute('project', result.project.id)
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      busy = false
    }
  }

  async function remove() {
    if (!deleting) return
    busy = true
    try {
      await request('project.delete', { projectId: deleting.id })
      appState.projects = appState.projects.filter((p: Project) => p.id !== deleting!.id)
      if (appState.projectId === deleting.id) appState.projectId = null
      deleting = null
      toast('success', 'Project deleted.')
    } catch (error) {
      toast('error', errorText(error))
    } finally {
      busy = false
    }
  }

  async function open(project: Project) {
    setRoute('project', project.id)
  }
</script>

<div class="page">
  <header class="page-head">
    <div>
      <div class="eyebrow">Library</div>
      <h1 style="margin-top:6px">Projects</h1>
      <p>Every room keeps its sources, transcripts, candidate moments and exports. Reopening restores the exact state.</p>
    </div>
    <div class="spacer"></div>
    <div class="row">
      <input class="input" bind:value={newName} placeholder="New project name" style="width:240px" onkeydown={(e) => e.key === 'Enter' && create()} />
      <Button variant="primary" disabled={busy || !newName.trim()} onclick={create}><Icon name="plus" size={15} /> Create</Button>
    </div>
  </header>

  {#if appState.projects.length}
    <div class="card tight" style="padding:8px 18px 18px">
      <table class="table">
        <thead>
          <tr><th>Project</th><th>Sources</th><th>Selected</th><th>Exports</th><th>Updated</th><th></th></tr>
        </thead>
        <tbody>
          {#each appState.projects as project (project.id)}
            <tr>
              <td>
                <button class="link" style="color:var(--text);font-weight:600;font-size:13px" onclick={() => open(project)}>{project.name}</button>
                <div class="tiny muted mono">{project.id.slice(0, 8)}</div>
              </td>
              <td class="mono">{project.counts?.sources ?? 0}</td>
              <td class="mono">{project.counts?.selections ?? 0}</td>
              <td class="mono">{project.counts?.exports ?? 0}</td>
              <td class="muted small">{new Date(project.updatedAt).toLocaleDateString()}</td>
              <td style="text-align:right">
                <div class="row tight" style="justify-content:flex-end">
                  <Button size="sm" variant="ghost" onclick={() => open(project)}>Open</Button>
                  <button class="icon-btn" title="Delete project" onclick={() => (deleting = project)} style="width:32px;height:32px">
                    <Icon name="trash" size={14} />
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="empty card">
      <Icon name="projects" size={40} />
      <h3>No projects yet</h3>
      <p>Create one above, or start from Home by importing a file or link.</p>
      <Button variant="primary" onclick={() => setRoute('home')}>Go to Home</Button>
    </div>
  {/if}

  {#if deleting}
    <div class="drawer-backdrop" onclick={(e) => e.target === e.currentTarget && (deleting = null)} role="presentation">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="eyebrow">Delete project</div>
        <h2>{deleting.name}</h2>
        <p class="soft">
          This removes the project, its source records, transcripts, candidates and edit settings from Clipwright.
          Exported video files in your output folder are not touched.
        </p>
        <div class="row" style="justify-content:flex-end">
          <Button variant="ghost" onclick={() => (deleting = null)}>Keep it</Button>
          <Button variant="danger" disabled={busy} onclick={remove}>Delete project</Button>
        </div>
      </div>
    </div>
  {/if}
</div>
