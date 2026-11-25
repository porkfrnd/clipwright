# Design system — the private desk

Clipwright is a private workspace with a cutting room behind it. The shell is a modern dark
productivity desk: a fixed 248 px rail, a 64 px top bar, near-black graphite, oversized sans
display type, one warm gold accent, and calm 18–20 px cards. It borrows the clarity of a good
dashboard without borrowing its fake metrics or growth theatre.

The rule is simple: real work in the foreground, one editorial gesture per screen, nothing
decorative that does not carry information. The supplied film-frame "C" is the brand mark and
the desktop icon; the boot sheet is a film leader, and the release page is a ledger.

The shipped screenshot set lives in [`docs/screenshots/`](screenshots/). It is captured from a
real Electron window with real fixture data and a real local Whisper transcript. Candidates are
authored for the showcase, as documented in `DEVLOG.md`.

## Themes

Dark-first. Every theme has exactly one hero accent and follows the user's appearance setting.
Tokens live in `apps/desktop/src/renderer/src/app.css` under `:root` and the theme selectors.

| Theme | Base | Surface | Hero accent | Character |
| --- | --- | --- | --- | --- |
| **Velvet** (default) | `#0e1113` | `#14181b` | `#d8a54b` brass | neutral graphite, warm highlight |
| **Ember** | `#13100e` | `#1a1613` | `#c98152` copper | brown-black, low warmth |
| **Slate** | `#0c1114` | `#131a1e` | `#84aeb8` blue-grey | cool, restrained |
| **Ivory** | `#eae7df` | `#f7f5ef` | `#2f5668` ink blue | light paper, dark ink |

The accent is for one thing at a time: the current selection, the primary action, a release
marker, or a live state. It is not a background wash and never carries meaning by itself.

### Contrast (token pairs)

Measured with the WCAG relative-luminance formula on text/surface token pairs. These are token
checks, not a full component audit.

| Theme | Body on surface | Muted on surface | Faint on surface |
| --- | --- | --- | --- |
| Velvet | 14.8:1 | 6.8:1 | 4.7:1 |
| Ember | 15.2:1 | 6.0:1 | 4.6:1 |
| Slate | 15.1:1 | 6.9:1 | 4.9:1 |
| Ivory | 15.4:1 | 5.2:1 | 5.8:1 |

All listed pairs meet WCAG AA for normal text. Color is never the only carrier of meaning:
statuses and categories always have a label or icon.

## Typography

Bundled OFL fonts. All are copied into the renderer at build time.

| Role | Family | Use |
| --- | --- | --- |
| Display | **Inter** | Page titles and the Home headline, at 600–650 weight with tight tracking. |
| UI sans | **Inter** | Body, controls, labels, navigation. |
| Mono | **JetBrains Mono** | Timecodes, segment IDs, versions, technical details, KPI figures. Never prose. |
| Subtitle display | **Bebas Neue** | Subtitle rendering only; it is a burn-in style, not chrome. |
| Archive accents | **Source Serif 4 / Archivo Black** | Reserved for the boot leader and rare editorial moments; not used for chrome. |

The identity is the pairing of a large, confident sans headline with compact mono metadata.
Do not reintroduce a serif page-title system or a second decorative display face.

Timecode typography is part of the identity: `00:00 → 00:16`, `FIT 86`, segment IDs in Details.
Numbers shown in the interface come from real data (projects, clips selected, exports validated,
minutes analyzed), never placeholder metrics.

## Shape and surface

- Radius family: `7px` controls, `10px` inputs, `12–14px` panels, `18–20px` workspace
  cards, full pill for primary actions and tags. Do not mix in a second rounded language.
- Cards use a **hairline border** plus a faint tonal lift, not a heavy drop shadow. The Home
  bench card is the one surface allowed a soft gold glow; it marks the active workspace.
- Hairlines are structural: section rules, table rows, ledger divisions, timeline ticks. They are
  not a border around every element.
- Primary actions are accent-filled with dark ink and a 999 px pill. Secondary actions are quiet
  ghost buttons. Destructive actions are text/outline until the confirmation step.
- The shell is a fixed 248 px rail, a 64 px top bar, a scrollable content column, and a status
  bar. The rail narrows and then becomes a compact strip below 980 px; content keeps a readable
  measure. At 1440×900 the Home fold shows the hero, bench, cut rail, KPI band, and the start of
  the drop zone without clipping.

## Signature: the film leader, the cut rail, and the release ledger

The boot screen is a film-leader sequence: frame count, gate marks, and a short set of boot
steps. It appears once and never blocks recovery; a failed engine can be retried or restarted
from the same sheet. The supplied gold "C" mark sits at the centre of the gate.

Home carries a four-step cut rail — Import, Read, Cut, Ship — as a real workflow map, not a
progress bar. The bench card on the right holds the last project or a first-source prompt, with
the 9:16 frame drawn in CSS. Together they are the two editorial gestures on the page; the KPI
band below is plain real counts.

The Updates page continues the same material language as a release ledger: installed and latest
versions set like titles, a rule between them, and a sparse sprocket perforation along the top of
the sheet. That perforation is the only decorative flourish on the page; everything else is
information.

## Domain visuals

### Moment map

A full-source horizontal strip showing transcript density behind the clip blocks, one block per
candidate colored by its primary category, height mapped to Clip fit, selection ticks, and a
playhead. It has keyboard slider semantics (`role="slider"`, arrow/Home/End handling) and
per-candidate buttons for keyboard users. Scrubbing seeks the preview; clicking a candidate
selects it and scrolls the list.

### Candidate card

Title, category pill + glyph, time range, duration, **Clip fit** ring, four compact rating meters
(Hook, Context, Ending, Clarity) with evidence on expand, weaknesses, and a one-line “why this
was picked”. Selection is unmistakable: accent edge, selected tick, and tray membership. Reject
and Preview are separate actions.

### Studio

The live preview is a 9:16 frame driven by the same settings the renderer uses: Fill, Blur fit,
Manual, static zoom, subtitle size/color/highlight/position/outline/max lines, safe margins,
music level, and output quality. A browser `<video>` approximates the burned subtitle overlay;
the export is still rendered by Python/FFmpeg and validated.

## Categories

Nine categories, each with a fixed color **and** icon, from
`apps/desktop/src/renderer/src/lib/categories.ts`:

| Category | Color | Icon |
| --- | --- | --- |
| Funny | `#c9a227` | laugh |
| Educational | `#6fa58a` | book |
| Storytelling | `#9b8bc4` | spool |
| Surprising | `#c97a6a` | spark |
| Emotional | `#be7c91` | heart |
| Controversial | `#c26a4a` | split |
| Insight | `#7e9fc4` | eye |
| Strong hook | `#d8a54b` | hook |
| Best overall | `#c4b07a` | star |

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
state, the boot leader. Durations are short (`120–260 ms`, `--ease`), and the “Reduce motion”
setting plus `prefers-reduced-motion` remove non-essential transitions. Effects can be disabled
independently. The update check never animates the whole shell.

## Accessibility

- Full keyboard navigation; visible `:focus-visible` rings in the theme accent.
- Semantic buttons, labels associated with inputs, ARIA roles on custom timeline controls.
- Body text ≥ 13 px and labels ≥ 11 px; no essential text is baked into images.
- Semantic status text accompanies color; category chips always include a label.
- Error messages are plain language with a stable code and a Details disclosure.
- Light and dark themes are checked at 1440×900, 1120×700 and 1600×1000.

## Screenshot coverage

| State | File |
| --- | --- |
| Populated Home, Velvet | [01-home-velvet](screenshots/01-home-velvet.png) |
| Discovery with candidates | [02-discovery-velvet](screenshots/02-discovery-velvet.png) |
| Compare two moments | [03-compare-velvet](screenshots/03-compare-velvet.png) |
| Studio | [04-studio-velvet](screenshots/04-studio-velvet.png) |
| Settings, appearance | [05-settings-velvet](screenshots/05-settings-velvet.png) |
| Privacy / what leaves the computer | [06-settings-privacy](screenshots/06-settings-privacy.png) |
| Model Manager | [07-models](screenshots/07-models.png) |
| Ivory light Home | [08-home-ivory](screenshots/08-home-ivory.png) |
| Ember Home | [09-home-ember](screenshots/09-home-ember.png) |
| Slate Home | [10-home-slate](screenshots/10-home-slate.png) |
| Compact density | [11-home-compact](screenshots/11-home-compact.png) |
| Small window 1120×700 | [12-home-small](screenshots/12-home-small.png) |
| Large window 1600×1000 | [13-discovery-large](screenshots/13-discovery-large.png) |
| Empty project | [14-empty-project](screenshots/14-empty-project.png) |
| URL validation error | [15-url-error](screenshots/15-url-error.png) |
| First-launch wizard | [16-wizard-welcome](screenshots/16-wizard-welcome.png) |
| Rate-limit wait with countdown | [18-rate-limit-wait](screenshots/18-rate-limit-wait.png) |
| Long project title | [19-long-title](screenshots/19-long-title.png) |
| Update available | [20-updates](screenshots/20-updates.png) |
| Update available | [20-updates](screenshots/20-updates.png) |

Re-capture with `node apps/desktop/tests/screenshots.mjs`,
`node apps/desktop/tests/ratelimit_shot.mjs`, and `node apps/desktop/tests/updates_shot.mjs`
after significant UI changes.
