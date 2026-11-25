# Design system — “Velvet”

Clipwright should read as a private screening room that happens to be software: near-black
surfaces, quiet rules, film-timecode details, and one decisive accent per theme. It is not a
generic dashboard and it does not use decorative AI imagery.

The shipped screenshot set is in [`docs/screenshots/`](screenshots/). It is captured from a
real Electron window with real fixture data and a real local Whisper transcript (candidates
are authored for the showcase, as documented in `DEVLOG.md`).

## Themes

Dark-first; every theme has exactly one hero accent. Theme tokens live in
`apps/desktop/src/renderer/src/app.css`.

| Theme | Base | Hero accent | Signature material | Screenshot |
| --- | --- | --- | --- | --- |
| **Velvet** (default) | `#0a0710` near-black violet | `#e8c77b` antique gold | film leader / gold rules | [01-home-velvet](screenshots/01-home-velvet.png) |
| **Ember** | `#0c0807` charcoal | `#ff7a45` signal orange | warm ember glow | [09-home-ember](screenshots/09-home-ember.png) |
| **Ivory** | `#f3eee4` warm paper | `#7a2333` oxblood | ink rules on paper | [08-home-ivory](screenshots/08-home-ivory.png) |
| **Slate** | `#080c0f` cool neutral | `#57c7bd` teal | cool grid | [10-home-slate](screenshots/10-home-slate.png) |

Dark/light is a separate control. Non-ivory themes have a light token pass; ivory is always
light. Density is `comfortable` or `compact`. Effects and reduced motion are honored globally,
including `prefers-reduced-motion`.

### Contrast (token pairs)

Measured with the WCAG relative-luminance formula on the text/surface token pairs. These are
token checks, not a full component audit.

| Theme | Body on surface | Muted on surface | Faint on surface |
| --- | --- | --- | --- |
| Velvet | 17.0:1 | 5.35:1 | 4.54:1 |
| Ember | 17.2:1 | 5.61:1 | 4.50:1 |
| Slate | 17.2:1 | 6.20:1 | 4.84:1 |
| Ivory | 15.0:1 | 4.63:1 | 4.68:1 |

All listed pairs meet WCAG AA for normal text. Color is never the only carrier of meaning:
statuses and categories always have a label or icon.

## Typography

Bundled OFL fonts, copied into the renderer at build time:

| Role | Family | Use |
| --- | --- | --- |
| Display | **Bebas Neue** | Page titles, hero numbers, big section labels; used with restraint, not for body text. |
| UI sans | **Inter** | Body and controls, ≥ 13 px body, ≥ 11 px labels. |
| Editorial display fallback | **Archivo Black** | Only where a heavier face is needed. |
| Mono | **JetBrains Mono** | Timecodes, segment IDs, technical details. Never prose. |

Timecode typography is part of the identity: `00:00 → 00:16`, `FIT 86`, segment IDs in
Details. Hero numbers come from real data (projects, shorts selected, exports validated,
minutes analyzed), never placeholder metrics.

## Shape and surface

- One radius family: `10px` small, `18px` standard, `26px` large, pill for buttons/chips.
- Cards are **borderless** and separated by tone and shadow, not outlines. No boxes inside
  boxes. One idea per card.
- Hairlines are reserved for structural rules and timeline ticks; the gold hairline is a
  material, not a border around everything.
- Primary actions are gold-filled pills with dark ink; secondary actions are quiet ghost
  pills; disabled actions lose contrast and never look primary.
- The layout is a fixed rail + top bar + scrollable content column. At compact widths the
  rail narrows; primary content keeps a readable measure.

## Domain visuals

### Moment map

A full-source horizontal strip. It shows:

- transcript density/waveform behind the clip blocks,
- one block per candidate, colored by its primary category,
- height mapped to Clip fit,
- selection ticks and a playhead,
- keyboard slider semantics (`role="slider"`, arrow/Home/End handling) and per-candidate
  buttons (`role="button"`, Enter/Space) for keyboard users.

Scrubbing the map seeks the preview; clicking a candidate picks it and scrolls the list.

### Candidate card

Shows title, category pill + glyph, time range, duration, **Clip fit** ring, four compact
rating meters (Hook, Context, Ending, Clarity) with evidence on expand, weaknesses, and a
one-line “why this was picked”. Selection state is unmistakable (gold edge + Selected).
Reject and Preview are separate actions.

### Studio

The live preview is a 9:16 frame driven by the same settings the renderer uses: Fill, Blur
fit, Manual, static zoom, subtitle size/color/highlight/position/outline/max lines, safe
margins, music level, and output quality. A real browser `<video>` preview approximates the
burned subtitle overlay; the export is still rendered by Python/FFmpeg and validated.

## Categories

Nine categories, each with a fixed color **and** icon, from
`apps/desktop/src/renderer/src/lib/categories.ts`:

| Category | Color | Icon |
| --- | --- | --- |
| Funny | `#f2c46d` | laugh |
| Educational | `#7fd1c1` | book |
| Storytelling | `#c9a7ff` | spool |
| Surprising | `#ff9db0` | spark |
| Emotional | `#f49ac1` | heart |
| Controversial | `#ff8a65` | split |
| Insight | `#8fb8ff` | eye |
| Strong hook | `#e8c77b` | hook |
| Best overall | `#d9c7ff` | star |

## Status map

| Status | Token | Glyph / treatment |
| --- | --- | --- |
| Success | `--success` | check, toast success |
| Warning | `--warning` | triangle, inline notice |
| Error | `--danger` | error glyph, notice with Details |
| Info | `--info` | info glyph |
| Waiting / rate limit | `--waiting` | pulsing dot + countdown copy |

Never use category color for status or status color for categories.

## Motion

Motion only explains a state change: progress bars, toast entry, panel transitions, preview
state. Durations are short (`120–260 ms`, `--ease`), and the “Reduce motion” setting removes
non-essential transitions. Effects can be disabled independently.

## Accessibility

- Full keyboard navigation; visible `:focus-visible` rings in the theme accent.
- Semantic buttons, labels associated with inputs, ARIA roles on custom timeline controls.
- Body text ≥ 13 px and labels ≥ 11 px; no text baked into images.
- Semantic status text accompanies color; category chips always include a label.
- Error messages are plain language with a stable code and a Details disclosure.
- Light and dark themes are tested at 1440×900, 1120×700 and 1600×1000.

## Screenshot coverage

| State | File |
| --- | --- |
| Populated Home, Velvet | [01-home-velvet](screenshots/01-home-velvet.png) |
| Discovery with 2 candidates | [02-discovery-velvet](screenshots/02-discovery-velvet.png) |
| Compare two moments | [03-compare-velvet](screenshots/03-compare-velvet.png) |
| Studio | [04-studio-velvet](screenshots/04-studio-velvet.png) |
| Settings, appearance | [05-settings-velvet](screenshots/05-settings-velvet.png) |
| Privacy / what leaves the computer | [06-settings-privacy](screenshots/06-settings-privacy.png), [06b lower](screenshots/06b-settings-privacy-lower.png) |
| Model Manager | [07-models](screenshots/07-models.png) |
| Ivory light Home | [08-home-ivory](screenshots/08-home-ivory.png) |
| Ember Home | [09-home-ember](screenshots/09-home-ember.png) |
| Slate Home | [10-home-slate](screenshots/10-home-slate.png) |
| Compact density | [11-home-compact](screenshots/11-home-compact.png) |
| Small window 1120×700 | [12-home-small](screenshots/12-home-small.png) |
| Large window 1600×1000 | [13-discovery-large](screenshots/13-discovery-large.png) |
| Empty project | [14-empty-project](screenshots/14-empty-project.png) |
| URL validation error | [15-url-error](screenshots/15-url-error.png) |
| First-launch wizard | [16-wizard-welcome](screenshots/16-wizard-welcome.png), [17 fresh profile](screenshots/17-first-launch-wizard.png) |
| Rate-limit wait with countdown | [18-rate-limit-wait](screenshots/18-rate-limit-wait.png) |
| Long project title | [19-long-title](screenshots/19-long-title.png) |

Re-capture with `node apps/desktop/tests/screenshots.mjs` and
`node apps/desktop/tests/ratelimit_shot.mjs` after significant UI changes.
