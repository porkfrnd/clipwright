<script lang="ts">
  let { name, size = 18, stroke = 1.7 }: { name: string; size?: number; stroke?: number } = $props()

  const paths: Record<string, string> = {
    home: 'M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5',
    projects: 'M3 6h6l2 2h10v11H3zM3 10h18',
    discovery: 'M3 12h4l2-6 3 12 2-6h7',
    studio: 'M4 5h16v14H4zM4 15l4-4 3 3 3-3 6 6M8 8.5h.01',
    settings: 'M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.56V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.11-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.5 15a1.7 1.7 0 0 0-1.56-1H2.9a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.5 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 8.86 4.5 1.7 1.7 0 0 0 9.9 3V2.9a2 2 0 1 1 4 0V3a1.7 1.7 0 0 0 1 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.5 8.9c.15.37.5.65.9.77',
    models: 'M12 3 3 8l9 5 9-5-9-5ZM3 12l9 5 9-5M3 16l9 5 9-5',
    film: 'M4 4h16v16H4zM8 4v16M16 4v16M4 8h4M4 12h4M4 16h4M16 8h4M16 12h4M16 16h4',
    scissors: 'M6 6a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM6 14a2 2 0 1 0 0 4 2 2 0 0 0 0-4ZM8 8l12 8M8 16 20 8',
    spark: 'm12 3 2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2L12 3Z',
    plus: 'M12 5v14M5 12h14',
    folder: 'M3 6h6l2 2h10v11H3z',
    play: 'm8 5 11 7-11 7V5Z',
    pause: 'M8 5v14M16 5v14',
    check: 'm5 12 4 4L19 6',
    alert: 'M12 3 2.5 20h19L12 3ZM12 9v5M12 17h.01',
    loader: 'M12 3a9 9 0 1 0 9 9',
    download: 'M12 3v12m0 0 4-4m-4 4-4-4M4 20h16',
    trash: 'M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6',
    key: 'M14 10a4 4 0 1 1-3.5 2.2L4 19v-3h3v-3h3l.5-1.5',
    mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3ZM5 11v1a7 7 0 0 0 14 0v-1M12 19v3',
    cloud: 'M7 18h10a4 4 0 0 0 .7-7.9A5.5 5.5 0 0 0 7.2 9 4.5 4.5 0 0 0 7 18Z',
    cpu: 'M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4',
    shield: 'M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z',
    clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2',
    star: 'm12 3 2.6 6.2L21 10l-5 4.3 1.6 6.7L12 17.6 6.4 21 8 14.3 3 10l6.4-.8L12 3Z',
    book: 'M4 4h7a3 3 0 0 1 3 3v14a3 3 0 0 0-3-3H4V4ZM20 4h-3a3 3 0 0 0-3 3v14a3 3 0 0 1 3-3h3V4Z',
    laugh: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM8 9h.01M16 9h.01M8 14s1.5 2 4 2 4-2 4-2',
    heart: 'M12 20s-8-4.5-8-10a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.5-8 10-8 10Z',
    eye: 'M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12Zm10 2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
    hook: 'M9 3h6v8a5 5 0 0 1-10 0M12 12v6a3 3 0 0 0 6 0',
    split: 'M4 3v18M20 3v18M8 8l4 4-4 4M16 8l-4 4 4 4',
    spool: 'M5 4h14v16H5zM5 8h14M5 16h14M8 4v4M16 4v4M8 16v4M16 16v4',
    info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 11v6M12 7h.01',
    external: 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
    refresh: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5',
    chevron: 'm9 6 6 6-6 6',
    more: 'M5 12h.01M12 12h.01M19 12h.01',
    x: 'M6 6l12 12M18 6 6 18',
    upload: 'M12 21V9m0 0 4 4m-4-4-4 4M4 4h16',
    target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM12 3v2M12 19v2M3 12h2M19 12h2',
    globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18',
    text: 'M4 5h16M12 5v14M8 19h8',
    volume: 'M4 9v6h4l5 4V5L8 9H4ZM17 9a5 5 0 0 1 0 6',
    frame: 'M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4'
  }
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={stroke}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
>
  <path d={paths[name] || paths.info} />
</svg>
