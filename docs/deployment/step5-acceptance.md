# Step 5 integration acceptance record

Date: 2026-10-07
Workspace: D:\\claudeCode\\rag_kb-integration
Branch: feat/frontend-backend-integration

Current local status (2026-10-08): Step 5 substep 8 local synthetic dual-frontend
acceptance is complete within the frozen v1 scope and the evidence boundaries
below. Browser automation is supplemented by user-performed Chrome Incognito
isolation and real WeChat IME checks on both frontends. Streamlit full-refresh
identity loss remains the expressly accepted v1 limitation, not a persistence
fix. Historical pending/failed entries below describe earlier stages; subsequent
follow-ups record their resolution. This is not production acceptance.

Closeout: owned local test services have been stopped and the two residual
synthetic runtime directories removed. See the
[reviewable delivery checklist](step5-delivery-checklist.md) for file scope,
validation results, incomplete repository gates, and the next handoff steps.
Local acceptance is complete. The 2026-10-08 repository follow-up below closes
the isolated test/coverage and formatting gates; real configuration security
and production acceptance remain outside this run. The later local-commit
authorization is recorded below; push and deployment remain unauthorized.

## Backend handoff

The deploy handoff was verified from shared local Git objects and the local
deploy/production ref. The complete handoff was received with
git merge --ff-only, preserving dependency history rather than selecting only
the final code commits.

- Source handoff: 9d42d19bc89fd26995b084828b39bf603483cda6
- Fixed limit/concurrency commit: 28c5c2552389f498d03e4a4a709400d0eab3b04b
- Fixed quota/session test commit: 86de66966a0fbd505faeb1d3a054696c768c795b
- Frozen contract body: 0f6ecf2ff2cec29158ea81616d6dbed4480dd67c
- Resulting integration HEAD: 9d42d19

No files were copied from the deploy working tree. No deploy temporary evidence
directories were merged. The deploy worktree was not modified.

## Frontend scope

v0.app-rag now uses same-origin /api requests and the backend-issued HttpOnly
anonymous session cookie. It initializes a session with
POST /api/session/anonymous, performs bounded recovery only for the contract's
invalid-session response, and keeps quota/identity decisions on the backend.

Implemented flows include suggestions, quota, library/document metadata, ask,
loading and duplicate-submit protection, answer/source rendering with escaped
expandable excerpts, explicit retry after network failure, structured 429/502/
503/504 handling, UTC reset-time display, mobile sidebar collapse, IME-aware
input, and the 2000 Unicode-character limit. Fictional recent conversations,
fictional library data, and non-functional settings were removed.

Next proxies /api to RAG_BACKEND_ORIGIN (default local origin
http://127.0.0.1:18000). It does not expose the backend hostname to the browser
and does not recreate the removed /ws/{client_id} endpoint.

## Verification

Completed locally:

- pnpm build: passed
- pnpm typecheck: passed
- pnpm lint: passed
- pnpm test: 18 tests passed
- http://127.0.0.1:3010/: HTTP 200 from the running Next server
- API tests cover concurrent session initialization/recovery, no automatic ask
  replay, structured status errors, non-JSON responses, nullable quota values,
  and the Unicode limit.

The local Next server is a frontend-only check. No real supplier/model call was
made. The automated API tests use synthetic responses and do not constitute
production acceptance.

## Local dual-frontend acceptance status

Historical result below is from 2026-10-07; see the 2026-10-08 browser follow-up
for newer evidence and remaining failures.

Step 5 substep 8 was run locally on 2026-10-07. Local HTTP/AppTest conditions
are available and the synthetic run passed; **交互式浏览器联验未执行**.
Tabbit SKILL.md was inaccessible, no Tabbit executable was discovered, and no
browser tool was available. Two independent HTTP cookie jars are not two
independent browser contexts and AppTest is not browser automation.

### Reproducible run and isolation

From the integration root in PowerShell:

```powershell
python scripts/acceptance/step5/local_dual_frontend.py
python -m pytest tests/test_demo_frontend.py tests/test_quota_frontend_contract.py --no-cov -q
Push-Location v0.app-rag
pnpm test
Pop-Location
git status --short --branch
git diff --check
```

- Synthetic FastAPI: `http://127.0.0.1:18080`.
- Existing Streamlit application: `http://127.0.0.1:18501`.
- Isolated Next source copy: `http://127.0.0.1:13010`, proxying `/api` to 18080.
- Original Next dev server on 3010 (PID 37088) was discovered and preserved.
- The runner creates a temporary directory inside integration, a fresh development
  ledger/reference, synthetic vector store and QA engine. It uses the real FastAPI
  application, identity, admission, concurrency, rate-limit and error handlers.
  Dotenv and ambient backend configuration sources are disabled. Provider/vector
  modules are replaced before application import; no supplier is called.
- Frontend subprocesses receive only OS launch variables and explicit test settings.
  Next source is copied without `.env*`, `.next`, or dependencies; a temporary
  junction reuses installed dependencies. All owned services stop after the run,
  and the successful run's temporary directory is removed. Final port check found
  only the pre-existing 3010 listener among the four ports.
- Early runs encountered the original Next dev lock, Windows cross-drive webpack
  resolution failure, and a nested `.next` source layout readiness timeout. The
  final runner uses a separate same-drive temporary source directory with webpack.
  These failed launches are not acceptance passes.

### Results and evidence boundaries

Final runner exit code: 0; **11 grouped checks passed**. Python frontend tests:
**21 passed** (focused `--no-cov` run, not a repository coverage gate). Next API
unit tests: **18 passed**. Earlier build/typecheck/lint results above were not
rerun because no Next product source changed in this substep. `isort` is absent
from the local Python environment; no full-repository lint pass is claimed.
The new runner and regression test pass Black's formatting comparison and Python
AST parsing. Final `git diff --check` passed; branch/HEAD remain unchanged and
all existing uncommitted work remains. Next `.next`, `node_modules` and
`.pnpm-store` are ignored.

| Area | Completed evidence | Boundary / pending work |
| --- | --- | --- |
| Identity and quota | Two Next HTTP cookie jars receive distinct backend cookies; HttpOnly and `/api` path checked; asking in A leaves B unchanged | Actual two-browser-context cookie behavior pending |
| Refresh | Homepage GET + repeated initialization retains cookie/quota; Streamlit AppTest rerun retains server token | Browser reload pending; Streamlit full reload/reconnect persistence not claimed |
| Suggestions/library/ask | Real routes through Next return synthetic document metadata, answer and citation payload | Document detail remains admin-only (anonymous 401); no new public detail endpoint |
| Streamlit | Actual identity helper produces independent server-session header identities/quotas; full homepage AppTest clicks suggestion and receives answer/source | Browser settings restoration is stubbed empty; no shared identity with Next assumed |
| 429 | Real personal quota and identity rate-limit rejections; request ID, no-store and Retry-After/reset metadata checked | Browser error rendering pending; Next parsing covered by unit tests |
| 503 | Real identity concurrency gate yields service_busy; lowering test global ask limit yields global_budget_exceeded | Synthetic admission conditions only |
| 504/502/counting | Engine double raises TimeoutError/failure; real route maps to upstream_timeout/upstream_error; timeout, failure and simulated cache hit each consume one admitted ask | No real supplier timeout/cache execution; no automatic refund |
| Nullable quota | Development-only quota toggle returns actual null daily_limit/remaining through Next | No production quota configuration changed |
| Unicode limit | 2000 astral characters accepted, 2001 rejected before admission; Next limiter unit test passes | Actual input/IME events pending |
| Rendering/escaping | Synthetic HTML-like answer/source payload reaches clients; Streamlit source escaping test passes; Next uses JSX text and details/pre elements | Browser answer/citation rendering and expand click pending |
| Network failure | Next unit test proves one rejected POST with no automatic replay; code inspection confirms explicit retry path | Actual browser network interruption and user retry pending |
| Mobile/IME/duplicate submit | Next code has initially collapsed sidebar, composition guards and synchronous busy guard | Mobile viewport, Chinese IME and rapid duplicate-click interaction pending |

### Integration defect fixed

The full Streamlit AppTest initially received `400 invalid_request`: empty BYOK
key plus default provider/model fields emitted partial `LLM-*` overrides, rejected
by the frozen backend contract. The main quota header builder, chat header builder
and document-manager header builder now omit all supplier overrides when the key
is empty. Chat still sends the backend-issued X-Anonymous-Token. Three regression
cases cover the default-settings condition. Backend contracts were not weakened.

### Remaining acceptance

Integration still needs the actual two-browser-context run, mobile/IME/duplicate
submission checks, visible error states, citation expansion and network-failure
explicit retry. The synthetic runner and frontend unit tests do not close those
items. Deploy should review/receive the Streamlit compatibility fix through the
normal handoff and retain responsibility for production acceptance. No push,
commit, production deployment, Docker operation or external message was performed.
The existing step5-integration-receipt.md was not rewritten.

## Browser follow-up: 2026-10-08 (partial acceptance)

Tabbit became available through the installed stable launcher with escalated
execution. The skill file exists; its previous access failure was a sandbox
permission issue. The CLI is not named `tabbit` on PATH:

```powershell
& "$env:LOCALAPPDATA\Tabbit\LocalAgent\bin\tabbit-cli.exe" diagnose
python scripts/acceptance/step5/local_dual_frontend.py --serve
```

`diagnose` returned `ok: true` / `controller: running`. Task
`Local dual frontend acceptance` used only its own newly created tabs. Local
services remain on backend 18080, Next 13010 and Streamlit 18501 for continuation.
Use Ctrl+C on the runner to stop its owned services and remove its temporary
directory. Runtime directories `/rag-step5-local-*/` are now ignored because
they contain disposable synthetic identities, not delivery assets.

Serve mode sets a synthetic personal limit of 50 and provides fixture-only
`POST http://127.0.0.1:18080/__fixture/control` with JSON `{"mode":"normal"}`.
Supported modes: normal, slow (4-second engine delay), quota_exceeded,
rate_limited, global_budget_exceeded, service_busy and upstream_timeout.
`GET /__fixture/status` returns only mode and request/engine counters.
These controls do not exist in the production app. Error modes synthesize the
real structured error handler's response **before admission**; they prove UI
presentation, not quota consumption. The 2026-10-07 tests separately exercised
actual admission/rate/concurrency/budget paths. Fault mode was restored to normal.

### Browser evidence

| Check | Result / scope |
| --- | --- |
| Next suggestions and ask | PASS: native suggestion click produced synthetic answer and one admitted ask |
| Next citation and escaping | PASS: citation expanded; source HTML-like text visible, zero script/img nodes in conversation |
| Next refresh persistence | PASS: cookie value compared in runtime without printing it; HttpOnly, `/api` path and used count retained after full reload |
| Next library | PASS: mobile sidebar lists synthetic-引用.md and one chunk |
| Next mobile | PASS at 390×844: sidebar initially collapsed, open/close controls work; screenshot visually inspected |
| Next Unicode limit | PASS: 1999 Chinese characters plus two astral characters truncated to 2000 code points without splitting the retained astral character |
| Next composition | PASS for dispatched events, plus user-reported real WeChat IME on Windows/Chrome Incognito: first Enter ended composition with literal zhongwen and no ask/count change (used 1); second Enter produced one answer and used 2, remaining 48 |
| Next duplicate submission | PASS for two immediate DOM click events while engine delayed: input disabled during work and used count increased by exactly one; not a physical touch double-tap test |
| Next network failure | PASS: page-scoped Playwright route.abort caused exactly one failed ask; no automatic replay during subsequent observation; removing route and clicking 明确重试上个问题 issued exactly one new POST |
| Next errors | PASS: all five requested structured errors display expected messages and request IDs; rate_limited/service_busy display 1-second retry wait |
| Streamlit initial load | Initially FAILED in isolated cwd (`No module named frontend`); runner now supplies explicit project PYTHONPATH; real page then loaded successfully |
| Streamlit suggestions/ask/library | PASS in actual browser with live fixture and normal settings restoration; answer and used count 1 displayed |
| Streamlit source rendering | PASS: source section collapsed/reopened; answer/source HTML-like payload rendered as text, zero script/img nodes inside assistant message |
| Streamlit errors | PASS for five injected errors. Timeout currently displays backend English message; no claim of localized 504 UX |
| Streamlit full browser reload | **Accepted v1 limitation, not a frozen-contract failure**: used count changed from 1 to 0 after full reload. Frozen contract §2.4 explicitly allows a new Streamlit session to lose its token; normal rerun retains identity. The earlier failure classification was incorrect. User explicitly chose to preserve the contract and add disclosure |
| Two independent browser contexts | **PASS for Next, mixed automated/manual evidence**: Tabbit A and Chrome Incognito B maintained independent quotas and retained them on reload. Tabbit browser.newContext() remains unsupported; the fallback uses genuinely separate browser storage, not two tabs in one context. Raw B Cookie values were not inspected |

The DeepL extension's `deepl-input-controller` intercepted pointer events over
Next's submit button during one test. That click timed out without an ask;
the documented Enter-submit action was then used. No user extension settings
were changed. Chrome Incognito was used for the independent-context continuation.

Screenshot: [Next mobile 390×844](receipts/step5-next-mobile-2026-10-08.png).

Tabbit request IDs supporting these results: `context-probe`,
`next-ask-citation-refresh`, `next-mobile-ime-double`, `streamlit-loaded`,
`streamlit-ask`, `streamlit-citation-next-recovery`, `next-network-enter`,
`next-network-explicit-retry`, `next-error-{code}`, `stream-error-{code}`,
`streamlit-reload-state`, `next-mobile-screenshot`. Error request suffixes are
the five mode names listed above. No Cookie/token values were exported.

### Independent-context continuation: passed with manual participation

Independent-context continuation (2026-10-08): the user opened Chrome Incognito
at the same `http://127.0.0.1:13010/` origin as context B and reported used 0,
remaining 50/50. Tabbit context A then submitted one synthetic question via the
UI: used 1 -> 2, remaining 49 -> 48; a full reload retained 2/48 (Tabbit request
`isolation-a-one-ask`). The user then reported B remained at used 0 / remaining
50 after refresh, submitted one question, received the synthetic answer and
source filename, and saw used 1 / remaining 49. B's subsequent full reload
retained 1/49. Finally, automated full reload and same-origin quota read in A
confirmed used 2 / remaining 48, daily limit 50 (`isolation-a-after-b`).

| Sequence | A: Tabbit (automated) | B: Chrome Incognito (user-reported) |
| --- | --- | --- |
| Baseline | Used 1, remaining 49 | Used 0, remaining 50 |
| After A submits once | Used 2, remaining 48; retained on reload | Used 0, remaining 50 after reload |
| After B submits once | Used 2, remaining 48 after reload | Used 1, remaining 49; retained on reload |

This establishes bidirectional quota isolation and reload persistence for Next
with mixed automated/manual evidence. It is not a fully automated two-context
test, nor direct inspection of B's Cookie attributes/value. No Cookie values
were requested from or shown to the user. B's visible synthetic answer included
literal `<script>alert(1)</script>` and source `synthetic-引用.md` as reported by
the user; no B DOM security inspection is claimed.

### Evidence boundaries after this follow-up

- Real WeChat IME has been user-verified on both Next and Streamlit; see the
  Streamlit completion record below. This does not cover every IME/browser.
- Synthetic UI fault results must not be treated as real supplier, production
  HTTPS, spend accounting, durable volume or backup/recovery acceptance.

### Streamlit remaining-items pass and contract correction (2026-10-08)

The user selected: preserve the frozen contract, add disclosure and acceptance
boundaries. Contract §2.4 expressly states that browser refresh/reconnection/new
session may lose the Streamlit token. No persistence bridge or client-side token
storage was added. The quota panel now explains current-page-session identity,
possible identity loss on full refresh/reconnection, separate frontend personal
quotas, and the shared global budget. Browser request `streamlit-session-notice`
confirmed the disclosure is present.

Additional changes and verified results:

- **Network failure:** Streamlit now presents a safe network/timeout message and
  an explicit retry button. Raw request exception details are not displayed.
  Rerun does not replay the ask or rotate identity. Clearing conversation clears
  its pending retry. Focused AppTest covers ConnectionError and Timeout, no
  replay on rerun, one explicit retry and retained header identity.
- **Loading/duplicates:** the initial live test found the old input remained
  enabled during the synchronous HTTP request. Submission now queues one
  validated question, reruns to render disabled controls, then executes it once.
  A processing guard rejects reentrant submission; clear-chat is disabled while
  busy. With the 4-second synthetic engine delay, two rapid native Enter events
  produced one ask, one settled assistant message and one admitted count. The
  input was visibly disabled while waiting (`streamlit-rapid-enter-fixed`).
  The first immediate DOM read saw transient rerun duplicates; a later exact
  count assertion confirmed one final assistant message (`streamlit-probe-open`).
- **Mobile:** initial_sidebar_state changed from expanded to auto. At 390×844,
  a full reload places the sidebar off-screen and leaves the input accessible.
  [Streamlit mobile screenshot](receipts/step5-streamlit-mobile-2026-10-08.png)
  was visually inspected; it captures the input/suggestions area after scrolling.
- **Unicode:** Streamlit 1.50's max_chars uses UTF-16 units: the old cap accepted
  2000 Chinese characters but refused 1001 emoji. The widget now permits 4000
  UTF-16 units, while Python rejects raw questions over 2000 Unicode code points
  before any ask. Live UI rejected 2001 Chinese characters with used count 0,
  accepted 2000 emoji, then rerun displayed used 1. No provider call was made.
  Tests include whitespace contributing to the raw-input limit. Overlong input
  must be shortened by the user; it is not silently truncated.

Reproducible real-response-loss browser probe (requires the main --serve runner):

```powershell
python scripts/acceptance/step5/streamlit_network_probe.py
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:18081/__probe/arm
Invoke-RestMethod -Uri http://127.0.0.1:18081/__probe/status
```

The auxiliary proxy on 18081 only forwards to the verified synthetic backend on
18080; its Streamlit instance listens on 18502. It forwarded one ask, waited for
the admitted backend answer, then shut down the TCP connection without returning
the answer to Streamlit. Browser `streamlit-response-lost` showed a safe network
error, used 1 / remaining 49 and an explicit retry button. Proxy status stayed
asks=1, dropped=1 during subsequent observation. Only after clicking explicit
retry (`streamlit-explicit-network-retry`) did counters become asks=2, dropped=1
and quota used 2 / remaining 48. This verifies response-loss/no-refund/no-auto-
replay behavior with a real local socket failure and synthetic QA, not a real
supplier or a physical network outage. The auxiliary browser page was closed
and the 18081/18502 processes stopped after acceptance; the main three services
remained running at that stage; they were stopped during final closeout.

Verification after the changes: 29 focused Python tests passed using
`python -m pytest tests/test_demo_frontend.py tests/test_quota_frontend_contract.py --no-cov -q`;
changed Python files were formatted with Black; `git diff --check` passed.
This is not a full-repository coverage/lint claim. No Next product source changed.

### Final manual IME check and local closure

The user tested Streamlit at `http://127.0.0.1:18501/` in Chrome Incognito using
WeChat IME in Chinese mode, without refreshing during the sequence:

| Action | User-observed result |
| --- | --- |
| Open page | Used 0 / 50, remaining 50 |
| Type zhongwen with candidate window open; first Enter | Candidate composition ended, literal zhongwen remained in the input; no answer and no quota change |
| Candidate window closed; second Enter | Exactly one synthetic answer; used 1, remaining 49 |

Result: PASS for the real IME composition/submit boundary on this tested setup.
This is user-reported manual evidence, not a synthetic event or an automated
inspection of the Chrome window. Next's equivalent manual WeChat IME check is
recorded above (used 1 -> 2 only after the second Enter).

The final pending local interaction item is now closed. Substep 8 is complete
for local synthetic acceptance with the explicitly accepted frozen-contract
Streamlit session limitation. Preserve the mixed evidence classification:
HTTP/admission tests, browser automation, fixture-injected UI errors, real local
socket response loss, and user-reported independent-context/IME checks are
different evidence sources. No real supplier or production validation is implied.
Deploy still needs to review/receive the integration changes and perform its
production-specific checks. All changes remain uncommitted; no push or deployment
was performed, and the existing integration receipt was preserved.

## Repository checks follow-up: 2026-10-08

Branch and full HEAD match the expected handoff. Existing uncommitted work and
the original integration receipt are preserved. No browser/IME acceptance was
repeated and no frontend services were restarted.

The workspace had no reusable venv. `.venv-step5-check` was created with Python
3.11.5 and `--system-site-packages`, then both repository requirements files were
installed using pip's isolated mode and the explicit public PyPI index. Missing
langchain-chroma 0.1.4 and isort 5.13.0 were installed; posthog 5.4.0 satisfies
the declared <6 constraint, and pipreqs 0.5.0 is an isort dependency. Global
Python packages and repository dependency declarations were not modified.

The new [repository check runner](../../scripts/acceptance/step5/repository_checks.py)
provides the reproducible command:

```powershell
& .\.venv-step5-check\Scripts\python.exe scripts/acceptance/step5/repository_checks.py
```

It retains pytest.ini's full tests and 70% gate, uses a temporary working and
user directory, removes inherited application settings, disables dotenv/keyring
reads, blocks business socket connections, and audits sensitive file opens.
Real application modules remain installed and importable; there are no missing-
module substitutes. Existing tests retain their own synthetic mocks/fixtures.
An initial all-socket block also broke Windows asyncio's internal socketpair;
that run was interrupted. The corrected runner permits only the standard
library socketpair caller's loopback connect and then reran the entire suite.

Final result: **685 passed in 101.83 seconds, coverage 80.56%, exit 0**.
All 3617 app statements remain in the coverage denominator (703 missed).
The earlier 12 collection errors/missing langchain_chroma blocker is resolved;
the earlier 16.59% collection-failure measurement is not a regression baseline.
Generated data, cache and HTML coverage report are disposable and removed on
normal exit after changing back from the temporary cwd.

Formatting and static checks:

- isort 5.13.0 `--check-only app/ tests/ frontend/ scripts/check_docs.py
  scripts/acceptance/step5/`: passed. Only TestClient's third-party import group,
  local runner import ordering, and test_demo_frontend mixed line endings needed
  correction; importorskip ordering remains unchanged.
- Black 24.8.0 API comparison of those directories/files: 90 Python files,
  none requiring formatting. The local Black CLI did not finish and was
  interrupted; this is explicitly an API comparison, not a CLI pass.
- flake8 on app/tests/check_docs and all three acceptance scripts with
  `--max-line-length=88 --extend-ignore=E203,W503`: passed.
- The earlier expanded frontend flake8 caveat remains; no unrelated cleanup.

The environment reuses system packages and is not a clean dependency lock.
`pip check` reports inherited unrelated-package conflicts: albumentations versus
pydantic, camelot-py versus pandas/pypdf, paddlex versus PyYAML, and pipdeptree
versus pip. This does not invalidate the observed project test pass, but no
environment-wide dependency-health pass is claimed. Do not deliver the venv;
deploy should install repository requirements in its own environment.

Tracked diffs, the untracked file manifest and Next core request/interaction
paths were reviewed. The delivery checklist now includes the new runner and
the small test import change. Original UI resources still require final commit
selection review; untracked status alone is not authorization to include them.
The code is ready for pre-commit review, with no automatic staging or commit.
`make check-security` remains unrun because it reads real settings/credentials;
that check requires deploy's separately authorized configuration environment.

Final checks: 54 Markdown files / 202 local links passed; git diff --check passed;
branch/HEAD unchanged. Six acceptance ports have no listeners, node_modules is
preserved, and the check venv/build artifacts remain ignored. The interrupted
first run's temporary directory was removed after validating its absolute path;
the successful run cleaned its own directory. No sensitive/runtime paths appear
in the untracked delivery manifest. No staging, commit, push, deployment, Docker
operation, external message, or deploy-workspace modification was performed.

## Local commit scope authorization: 2026-10-08

After the checks above, the user explicitly authorized reviewing the delivery
scope and creating a local commit, excluding the original integration receipt
and without pushing. Scope review passed: 8 modified files and 95 new files,
including the Next source, configuration, lockfile, existing UI components and
static assets, Python frontend fixes/tests, three acceptance runners, two mobile
screenshots and the two delivery records. Runtime data, dependencies, caches
and the check venv are excluded. `step5-integration-receipt.md` remains untouched
and untracked. Earlier statements about uncommitted status describe those earlier
stages; this delivery commit records the subsequent authorization. Staged diff
checking found extra EOF blank lines in layout.tsx and the two use-toast.ts files;
only those trailing blank lines were removed. No product logic changed, and
browser acceptance was not
repeated. The commit's parent is the recorded backend handoff; its Git identity
provides the fixed version for a separately authorized future handoff.

## Remaining handoff boundaries

Production deployment and cloud acceptance remain with deploy. This integration
record does not claim real supplier behavior, production spend limits, durable
volume/backup recovery, public HTTPS, or the complete production dual-frontend
browser path. The existing Streamlit lint caveat also remains unchanged.
