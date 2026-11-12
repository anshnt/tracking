# Design notes

Hallmark app-screen pass, theme Ultraviolet (lavender), Geist for everything, Geist Mono for figures, IDs, hashes and code. Light only. Sentence case everywhere. Never use an em dash.

## Rules

- Violet marks only: the page's one primary button, the current nav item or tab, focus. Nothing else is chromatic except state tones (green, amber, red).
- Surfaces: page on `--color-paper`, panels and sidebar on `--color-paper-2`, no borders on surfaces, hairline (`--color-rule`) rows. One container recipe (`.panel`); never a panel inside a panel.
- Tables before cards. Controls are pills, 36px tall (`--control-h`). No icon tiles, gradients, glow, emoji, tracked caps, eyebrows, invented figures, scores or rankings.
- Every colour via a token (tokens.css), every font via a token. Never `transition: all`. Every interactive element has `:focus-visible`.
- Every data region has four states: loading (skeleton, after 150ms), empty (what belongs here plus one action), error (what broke plus retry), full.
- State must carry a text label; the glyph in a pill is a bonus, not the signal.

## Tokens (tokens.css)

Paper `--color-paper`, `-2`, `-3`; ink `--color-ink`, `-2`, `--color-muted`; `--color-rule`, `--color-rule-2`; accent `--color-accent`, `-deep`, `-soft`, `-ink`. State tones: `--tone-ok`, `--tone-warn`, `--tone-bad` (text) with `-soft` grounds. Spacing `--space-*`, type `--text-*`, fonts `--font-body`, `--font-outlier` (mono). Sizes in styles.css: `--control-h`, `--control-h-sm`, `--radius-field`, `--page-max`.

## Components (`components/ui.tsx`, re-exports the rest)

| Component | Use |
| --- | --- |
| `Page({title, lead, actions})` | Every screen. `lead` is one line. `actions` holds the one primary button. |
| `Section({title, hint, actions})` | Headed group on the page ground. Put tables here. |
| `Panel({title, hint, actions})` | Same, on a paper-2 surface: forms, grouped facts. |
| `DataTable({label, sticky})` | Wraps `thead`/`tbody`. Row header is `<th scope="row">`; numbers get `className="num"`; IDs and hashes `className="mono"`. |
| `Toolbar({label})` | Filter row above a table: inputs, selects, `Button variant="quiet"`. Keep filters in the URL. |
| `StatusPill({tone, children})` | `tone` is `ok`, `warn`, `bad` or `muted`. Also `StatusTag status="in_progress"` (raw API status), `PostureBadge state`, `Tag`. |
| `Button({variant})` | `primary` (violet), `secondary` (default, ink ring), `quiet`, `danger`. Anchors: `className="btn btn-primary"`. Bare `<button className="primary">` still works. |
| `Field({label, hint, error, required})` | One input, select or textarea as the child; wires id, `aria-describedby`, `aria-invalid`. |
| `Async({load, skeleton, rows, isEmpty, empty})` | Skeleton, error with retry, optional empty, then content. `skeleton` is `rows`, `lines` or `block`. |
| `Skeleton`, `EmptyState({title, action})`, `ErrorState({message, onRetry})` | Use directly where `Async` does not fit. `Empty` is the legacy one-liner. |
| `NoticeCard` | The signature. Props: `title`, `status`, `meta`, `recorded[]`, `never[]`, children (notice text), `contact`, `hash`, `action` (acknowledgement control). |
| `KeyValue({items})` | A `dl` of label and value pairs. |
| `Ts({iso})` | Timestamp in the viewer's zone. |
| `Result`, `useAction`, `useLoad`, `useMe`, `errText` | Unchanged. |

Shell (`components/Shell.tsx`): `AppFrame` (sidebar, top bar breadcrumb, content column), `SideNav`. Under 60rem the sidebar is a menu: `aria-expanded`, Escape closes, focus returns to the Menu button. The `js` class on `<html>` (set in main.tsx) gates the hidden-at-rest sidebar.

## Legacy classes still styled

`.card`, `.meta`, `.muted`, `.mono`, `.wrap`, `.prose`, `.tablewrap`, `.tabs`, `.split`, `.row`, `.form`, `.check`, `.msg`, `.badge`, `ul.plain`, `ul.cards`, `dl.kv`. New screens should use the components above instead.
