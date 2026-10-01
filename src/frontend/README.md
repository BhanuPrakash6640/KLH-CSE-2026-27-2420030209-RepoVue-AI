# RepoVue — Web client

The reviewer's side of the pipeline. Eight screens, no build-time data: every
number on screen comes from the API, and anything the API could not produce is
shown as absent rather than faked.

React 18 + TypeScript + Vite, with React Router. No component library, no CSS
framework, no data-fetching library — the design brief specifies the whole
visual system as tokens, and the API is small enough that a typed `fetch`
wrapper and one polling hook cover it.

---

## Screens

| Route | What it is for |
|---|---|
| `/` | Every connected repository with its last run and what that run left behind |
| `/new` | Start a run: branch, commit or PR, which categories to look for |
| `/analyses/:id` | The run. Live pipeline while it works, dashboard once it finishes |
| `/analyses/:id/findings` | The findings table: filter, page, keyboard-drive |
| `/findings/:id` | One finding: provenance, the code, the reasoning, your verdict |
| `/patches/:id` | The patch, the diff, and the test run that judged it |
| `/analyses/:id/search` | Hybrid search over the same index the review used |
| `/settings` | API key and service status |

`/analyses/:id` is deliberately one URL for both states. A link to a run works
whether or not the run has finished by the time someone opens it.

---

## Things worth knowing

**Polling, not websockets.** A running analysis is re-fetched every 2.5s and
polling stops the moment the run reaches a terminal state. The backend already
writes `stage` and `progress` on every stage transition, so this costs one
endpoint and no server-side connection state.

**The stage timeline is derived, not stored.** The nine stages are known
constants; the detail line under each one is built from whatever
`analysis.stats` currently holds. A stage that has not run yet says what it
will do, rather than showing an empty row.

**Diffs are parsed, not pattern-painted.** `components/Diff.tsx` reads the hunk
headers and tracks both gutters, so the old and new line numbers are the real
ones. It is the one piece of display logic with real edge cases, so it is the
one piece with tests.

**Snippet line numbers are reconstructed.** The backend stores two lines of
context either side of a finding (`_snippet` in `services/analyzers.py`), so the
first rendered line is `start_line - 2` and the cited lines can be marked
without storing per-line metadata. If that padding changes server-side, change
the `pad` prop with it.

**The verdict buttons are the product's own scorecard.** `PATCH /findings/{id}`
is how precision gets measured instead of guessed at, so marking a finding
wrong is presented as the useful act it is, not as a complaint.

**Absent capability is stated, not hidden.** No model key or no Docker on the
host changes what a run can produce. The sidebar and the Settings screen say so
directly, and patch pages say "not validated" rather than implying a pass.

---

## Running it

```bash
npm install
cp .env.example .env      # optional; defaults work against a local API
npm run dev               # http://localhost:5173, /api proxied to :8000
```

Point the dev proxy somewhere else with `VITE_PROXY_TARGET=https://host npm run dev`.

```bash
npm run build       # tsc -b && vite build  → dist/
npm run test        # vitest
npm run typecheck
```

In Docker, `docker compose up --build` serves the built client on
<http://localhost:3000> with nginx proxying `/api` to the API container, so the
browser makes same-origin requests only.

---

## The API key

Sent as `X-API-Key` on every request. It comes from `localStorage`, falling
back to the `VITE_API_KEY` baked in at build time. The Settings screen changes
it without a rebuild, which is what you want when one build serves several
environments. It is a shared secret, not a user identity — there is no login
here because there are no users in the schema yet.

---

## Layout

```
src/
  lib/        api client, response types, display helpers, hooks
  components/ sidebar, severity marks, code snippet, diff, states
  pages/      one file per screen
  styles.css  the design tokens, verbatim from the brief
```

Colour, spacing and type all come from CSS custom properties on `<body>`.
Theme (light/dark) and density (comfortable/compact) are attributes on that
same element, which is why switching either one costs no re-render of anything
but the toggle.
