# RepoVue

AI-powered codebase analysis for automated bug detection and optimization.
API, worker and web client in one repository.

Point it at a GitHub repository. It builds a structural map of the code, reviews it
with an LLM, writes minimal patches for what it finds, **proves each patch in a
container against the project's own test suite**, and opens a pull request with only
the fixes that passed. Confirmed issues become Jira tickets.

The validation step is the part that matters. Anything can print a list of suspected
bugs; this runs the tests before and after the patch and throws away the ones that
regress.

---

## Pipeline

```
clone → index (AST + graphs) → embed → AI review → triage
      → fix generation → Docker validation → GitHub PR / check run → Jira
```

| Stage | What happens | Module |
|---|---|---|
| clone | Shallow clone at a ref, size-capped, token-authenticated | `services/github.py` |
| index | Tree-sitter ASTs → symbols, call graph, dependency graph, hotspots | `services/ast_parser.py`, `services/graphs.py` |
| embed | Symbol-aligned chunking → embeddings → pgvector | `services/chunker.py`, `services/embeddings.py` |
| review | Rule pre-scan + 4 category analyzers per file, run in parallel | `services/analyzers.py`, `services/rules.py` |
| triage | Separate adversarial pass whose only job is deleting false positives | `services/analyzers.py` |
| fix | Model returns a region replacement; difflib builds the diff | `services/patcher.py` |
| validate | Docker: baseline tests+timing → apply → re-run → verdict | `services/sandbox.py` |
| publish | Check run (quality gate), inline PR review, fix PR | `services/github.py` |
| jira | Tickets for confirmed findings above a severity floor | `services/jira.py` |

Orchestrated by `pipeline/orchestrator.py`. Every stage writes `stage`/`progress` to
the `analyses` row, so the frontend gets a live progress bar for free.

---

## Design decisions worth defending

These are the choices that separate this from a wrapper around a chat model.

**The LLM never writes the diff.** Model-authored unified diffs fail `git apply`
constantly — wrong hunk headers, drifting context. Instead the model returns a
replacement for an explicit line range, we splice it into the real file, generate the
diff with `difflib`, and verify with `git apply --check` before it goes anywhere.

**Structured output is enforced, not parsed.** Every analyzer answers through a tool
whose `input_schema` *is* the response shape, with `tool_choice` forcing it. No regex
hunting for JSON in prose.

**Deterministic rules feed the prompt, they don't produce findings.** ~25 regex
detectors run first and are injected as "suspicious regions the model should verify."
A regex false positive can never reach the user on its own.

**A dedicated triage pass.** A second model call reviews every candidate finding and
deletes the weak ones. False positives destroy trust faster than misses do, and this
is the lever that controls them.

**Fingerprints, not line numbers.** Findings are keyed by
`category + path + title signature + normalised code`, so an added import doesn't
re-report every issue in the file, and Jira doesn't accumulate duplicates.

**Postgres job queue, not Redis + Celery.** `SELECT … FOR UPDATE SKIP LOCKED` gives
durable claiming across as many workers as you want, using the database you already
have. One less service to run and explain.

**File selection is budgeted.** On a large repo, reviewing every file is money set on
fire. Files rank by changed-in-this-PR > hotspot score > complexity, capped at
`MAX_LLM_FILES`.

---

## Running it

### Docker (everything: Postgres with pgvector, API, worker, web client)

```bash
cp .env.example .env      # add ANTHROPIC_API_KEY and GITHUB_TOKEN
docker compose up --build
open http://localhost:3000        # the web client
open http://localhost:8000/docs   # the API
```

nginx serves the built client and proxies `/api` to the API container, so the
browser only ever makes same-origin requests.

### Local against Neon

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # set DATABASE_URL to your Neon URL, DB_SSL=true

python -m app.db.init_db          # creates extensions, tables, HNSW index
uvicorn app.main:app --reload
```

And the client, in a second terminal:

```bash
cd frontend
npm install
npm run dev                       # http://localhost:5173, /api proxied to :8000
```

`RUN_WORKER_IN_API=true` runs the worker inside the API process — fine for
development. In production set it to `false` and run `python -m app.worker.tasks`
separately, so a 10-minute Docker validation never blocks HTTP requests.

### Demo

```bash
./scripts/demo.sh https://github.com/some/repo
```

### Tests

```bash
pytest -q                    # 56 tests, no DB / API key / Docker required
cd frontend && npm test      # 14 tests: diff parsing and display helpers
```

The backend suite includes `tests/test_api_contract.py`, which asserts against
the generated OpenAPI document that every endpoint and field the web client
reads still exists. Rename a response field and that suite fails before the
client does.

---

## Configuration

Everything is env-driven; see `.env.example` for the full list. The ones that change
behaviour most:

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Without it, indexing still runs; review and fix stages skip |
| `EMBEDDING_PROVIDER` | `voyage` | `voyage` \| `openai` \| `hash`. `hash` is a real offline projection so the pipeline runs with no key |
| `VALIDATION_ENABLED` | `true` | Set false if the host has no Docker socket |
| `LLM_MAX_CONCURRENCY` | `4` | Caps in-flight model calls; raise if you have headroom |
| `PERF_REGRESSION_TOLERANCE` | `0.05` | Patch is rejected if runtime worsens more than this |
| `JIRA_MIN_SEVERITY` | `high` | Severity floor for ticket creation |
| `API_KEYS` | `dev-local-key` | Comma-separated; sent as `X-API-Key` |

---

## API

Interactive docs at `/docs`; the OpenAPI schema at `/openapi.json` is enough to
generate a typed frontend client.

```
POST   /api/v1/repositories              register a repo
GET    /api/v1/repositories
GET    /api/v1/repositories/overview     every repo + its last run  ← repositories table
GET    /api/v1/repositories/{id}

POST   /api/v1/analyses                  queue an analysis (202, poll for result)
GET    /api/v1/analyses/{id}             status + stage + progress
GET    /api/v1/analyses/{id}/summary     everything the dashboard needs, one call
GET    /api/v1/analyses/{id}/files
GET    /api/v1/analyses/{id}/graph
GET    /api/v1/analyses/{id}/gate        quality gate — what CI polls
DELETE /api/v1/analyses/{id}

GET    /api/v1/findings                  filter by analysis/severity/category/path/q
GET    /api/v1/findings/{id}             finding + its patches
PATCH  /api/v1/findings/{id}             mark false positive / resolved  ← feedback loop
GET    /api/v1/findings/{id}/jira

GET    /api/v1/patches
GET    /api/v1/patches/{id}
GET    /api/v1/patches/{id}/validations  baseline vs patched, tests + timings
POST   /api/v1/patches/{id}/decision     accept / reject

POST   /api/v1/search                    hybrid vector + lexical code search
POST   /api/v1/webhooks/github           HMAC-verified webhook
GET    /api/v1/health  /api/v1/metrics
```

`PATCH /findings/{id}` is how you measure precision honestly instead of guessing at
it — every false positive a reviewer marks is a data point for the evaluation phase.

---

## CI integration

`.github/workflows/repovue.yml` drops into any target repo. It queues an analysis,
polls the gate, writes a job summary and fails the build on blocking findings. It
needs two secrets: `REPOVUE_URL` and `REPOVUE_API_KEY`.

For push/PR-driven analysis without an Action, point a GitHub webhook at
`/api/v1/webhooks/github` and set `GITHUB_WEBHOOK_SECRET`.

---

## Schema

`repositories → analyses → {source_files, symbols, call_edges, dependency_edges,
code_chunks, findings → patches → validation_runs}`, plus `pull_requests`,
`jira_tickets` and `jobs`.

Everything hangs off an analysis, so re-running is idempotent and historical runs stay
queryable for trend charts. `code_chunks.embedding` is a pgvector column with an HNSW
cosine index.

`app/db/init_db.py` handles first-run setup. Move to Alembic before you have data you
care about.

---

## Language support

Full AST extraction: Python, JavaScript, TypeScript, TSX, Java, Go, Ruby, PHP, Rust,
C, C++, C#, Kotlin. Adding one is roughly four lines in the node-type maps in
`services/ast_parser.py` — no per-language query files to maintain. Unsupported
grammars degrade to an error on the file record rather than failing the analysis.

Sandbox build templates ship for Python, Node, Go and Java; a repo with its own
Dockerfile uses that instead.

---

## Known limitations

Worth knowing before you demo it rather than discovering live:

- **Call graph resolution is name-based.** Duck typing, dynamic dispatch and
  decorators resolve heuristically (same-file candidates win). Good enough for
  ranking and context; not a substitute for real type inference.
- **Validation needs a test suite.** No detectable test command → verdict is
  `skipped`, not `pass`. Patches still generate, they just carry less evidence.
- **Baseline must be green.** If the project's tests already fail, we can't attribute
  anything to the patch, so validation reports `skipped` with that reason.
- **Timing benchmarks use median wall-clock** over `BENCHMARK_RUNS` executions of the
  test suite. Fine for catching a 10× regression; too noisy for micro-optimisation
  claims.
- **Fingerprint rephrasing.** A heavy rewording of the same issue
  ("X in Y" → "Y allows X") can still produce a second fingerprint. Tracked for the
  evaluation phase.
- **No auth beyond API keys.** Multi-tenant work (orgs, per-user scoping, GitHub App
  installation tokens) is scaffolded in the schema but not implemented.

---

## The web client

`frontend/` — React + TypeScript + Vite, no component library. The design system
is a set of CSS custom properties (light/dark, comfortable/compact) and every
number on screen comes from the API; nothing is stubbed. See
[`frontend/README.md`](frontend/README.md).

Eight screens: repositories, start a run, the live pipeline, the run dashboard,
the findings table, one finding, one patch with its test run, and code search.
`/analyses/{id}` is one URL for both the running and finished states, so a link
to a run works whenever someone opens it.

Two decisions worth defending here as well:

**The diff is parsed, not pattern-painted.** Hunk headers are read and both
gutters tracked, so old and new line numbers are the real ones. It is the only
display logic with real edge cases, so it is the logic with tests.

**Missing capability is stated, not hidden.** Without a model key the review and
patch stages skip; without Docker nothing is validated. The sidebar, the
Settings screen and every patch page say so, rather than letting an unvalidated
patch look like a passing one.

---

## Evaluation, and what is not done yet

The pipeline, the API, the CI integration and the client are all implemented.
What remains is the measurement in section 11 of the project plan — detection
accuracy, false-positive rate and patch success rate — which needs a corpus of
seeded repositories with known bugs to run against.

The instrumentation for it already exists and is deliberately not optional:
`PATCH /findings/{id}` records a reviewer's verdict, the finding detail screen
asks for that verdict in as many words, and `/metrics` reports the running
false-positive count. The numbers come from reviewers using the tool, not from
a self-assessment.
