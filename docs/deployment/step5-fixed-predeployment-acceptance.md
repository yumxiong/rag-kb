# Step 5 fixed-version predeployment acceptance

Date: 2026-10-10. Workspace: `D:\claudeCode\rag_kb-deploy`.

Result: local container, admission, synthetic storage, and browser 75-second
timeout checks passed. Explicit retry passed after reopening the page with the
same identity following a Tabbit task/page loss, as detailed below.
This record does not authorize production deployment.

## Fixed source and builds

- Commit: `62d4cffbaad0a84b6f2def76f3dbd992d3f53bb9`.
- Branch at start: `deploy/production`, synchronized with `origin/master`.
- Tracked files and index were clean. Existing `.step4-evidence/` and
  `.step4-run/` were neither read nor changed.
- Build inputs were exported from the fixed Git object into the ignored
  `rag-step5-local-fixed-62d4cff/source` directory. All 144 checked application,
  frontend, requirements, and Dockerfile inputs matched that commit; 125 text
  files had only Git `core.autocrlf` line-ending conversion.
- Backend and Streamlit were built using the repository Dockerfiles and
  requirements with `PIP_INDEX_URL=https://pypi.org/simple`. Both images passed
  offline `python -m pip check`.
- Next build passed using matching BuildKit cache and the frozen pnpm lockfile.
- Initial backend resolution failed with `protobuf` unavailable and
  `ResolutionImpossible`. A subsequent official-index query found distributions;
  retrying the same build without source or dependency changes succeeded.
  Root cause was not conclusively established. Python transitive dependencies
  remain unlocked; preserve the accepted image digests instead of assuming a
  future rebuild will resolve the same environment.

Local image IDs:

| Image | SHA-256 |
| --- | --- |
| `rag-step5-backend:62d4cff` | `38f92c22e43aef4729f0215efe7719315ae073ea7068b3bf7b638a212e614b1f` |
| `rag-step5-streamlit:62d4cff` | `332f6a72f66b7206b745f4a55f2a25a6050772e4101e4790173248d77591583f` |
| `rag-step5-next:62d4cff` | `770ec2eace84c54ac036ccd56cb5597f5e0594d8c83a9f51a6795496687948f5` |
| `nginx:1.28-alpine` | `a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236` |

These are local Docker image IDs, not evidence of registry publication.

## Dual-host gateway and real admission

Project `rag-step5-fixed` used the fixed Next and Streamlit Nginx templates,
rendered only for local test hosts and temporary certificates. Only the gateway
published a host port: `127.0.0.1:18443`. Backend, Next, Streamlit, and the test
delay service used an internal network. No production configuration, ledger,
logs, or provider credentials were mounted. Compose dotenv loading was disabled.

The backend ran code packaged in the newly built image, rather than an old image
with application-source mounts. The fixture disabled real configuration/key
loading and outbound socket connections, and used a disposable tmpfs ledger.
Vector retrieval and the question engine were synthetic; identity, routes,
admission, counters, leases, and deadlines used real backend implementations.

Passed:

- Combined `nginx -t`; Next page and static asset; Streamlit page and health.
- Both hosts: public library 200, anonymous document detail 401, disabled docs
  and obsolete `/ws/` 404.
- Streamlit WebSocket upgrade 101 after declaring its external test hostname.
- Independent cookie identities, identity reuse, untrusted Origin 403 without
  charge, admitted failure/cache counting, and sixth-question quota rejection.
- Early disconnect counted once without refund/replay; worker retained its
  concurrency slot; explicit retry succeeded after worker completion.
- Real 60-second deadline, slot retained while the worker finished, and recovery
  without refund.

The first Streamlit WebSocket probe returned 403 with the test Origin. Setting
`STREAMLIT_BROWSER_SERVER_ADDRESS=st.localhost` on the disposable Streamlit
container changed it to 101, without disabling CORS or XSRF protection. Actual
production configuration must declare/verify the real Streamlit hostname. No
claim is made that the unread existing production configuration has this defect.

## Synthetic persistent-volume recovery

Four newly created, separately named Docker volumes held synthetic ledger,
independent reference, backup, and restored data. No existing volume was reused.
The fixed backend storage implementation ran with `development=False`, actual
Linux mount-source validation, atomic writes, and directory fsync.

Passed initialization and admission; a new container retained the synthetic
identity, personal count, ask budget, and provider-attempt budget. A stopped-store
backup restored into a separate new volume retained the same values. An incorrect
reference UUID and a missing mount both failed closed with
`quota_storage_unavailable`/503 rather than reinitializing. Test volumes were
removed after the checks.

This is a local storage-mechanism drill, not production backup/restore acceptance,
power-loss testing, or a measured production RPO/RTO guarantee.

## Browser timeout: initial attempt incomplete

Tabbit registration initially failed; the user restarted Tabbit and access
recovered. The local Next page loaded using an explicit exception for this
synthetic self-signed certificate; no system trust store was changed.

After the direct gateway checks passed, only the temporary gateway ask route was
changed to a one-attempt delay service. For `browser-timeout`, it forwards to real
backend admission and delays the completed response for 85 seconds. This isolates
the frontend's 75-second wait boundary without changing the backend deadline.

A browser extension intercepted the initial submit-button click. Before using
the normal Enter action, quota and proxy checks confirmed zero requests had been
sent. Enter then sent one request. During the wait, Tabbit returned
`OUTCOME_UNKNOWN` because its Runtime generation restarted. The test page was
absent from the recovered browser inventory. The proxy subsequently reported
exactly one attempt and one delayed response; the question was not replayed.

The initial attempt did not establish the visible timeout message, exact elapsed
time, post-timeout UI state, or explicit browser retry. It was not counted as a
pass. The targeted follow-up below supplies the subsequent evidence.

## Browser timeout follow-up: passed with retry evidence boundary

The targeted follow-up on 2026-10-10 reused the fixed images and isolated project.
The temporary delay fixture delayed only the first `browser-timeout` response by
85 seconds; a subsequent explicit submission of the same question returned
normally. It recorded the downstream connection-close interval. No application
code, browser timer, or backend deadline was changed.

The browser initially retained an identity from the destroyed previous tmpfs
ledger. The backend correctly rejected it. Only the `rag_anonymous` cookie for
`localhost` was cleared to establish a fresh synthetic identity; no question had
been sent at that point.

| Check | Observed result |
| --- | --- |
| Initial explicit Enter submission | One browser ask POST, one upstream attempt; quota 0 to 1 |
| Waiting state | Actual page displayed the generating state; quota already 1 |
| Visible timeout | At 75,033.1 ms, the actual page displayed “等待回答超过 75 秒，可能已计次数。请稍后主动重试。” |
| Transport cancellation | Delay service observed downstream close at 75,010 ms, before its 85-second response and Nginx's 90-second timeout |
| UI recovery | Question textbox enabled after the timeout |
| No automatic refund/replay | Quota stayed 1; browser POST count and upstream attempts stayed 1 |
| Explicit retry | After reopening with the same cookie, quota remained 1 and upstream attempts remained 1; explicit Enter submission of the same question returned `synthetic answer`, quota became 2, and total upstream attempts became 2 |

The timeout timing was measured with a DOM MutationObserver that only observed
the actual message; it did not alter request behavior or accelerate time.
The message appeared in both the global alert and conversation; the visibility
assertion was scoped to the conversation. The cancellation interval independently
corroborated the visible timing.

After the timeout assertions succeeded, Tabbit lost the task/page before the
planned retry. The retry program failed at its first read, before sending a
request. Inventory confirmed the original page was absent. Reopening the test URL
retained the same cookie and recovered quota=1; the subsequent explicit retry
passed. Thus retry is verified after page reopening, not as an uninterrupted
same-page sequence. Original-page input recovery was verified before that loss.
No IME or cross-browser coverage is added by this follow-up.

The proxy/engine remained synthetic, while session, admission, and quota were
real backend logic. This verifies frontend timeout and transport behavior, not a
real supplier timeout or provider cancellation. The browser used the local
self-signed certificate exception already established for this test host.

## Remaining boundaries and next actions

1. Review real deployment configuration under separate authorization: both hostnames,
   certificates, Streamlit external hostname, exact Next Origin, trusted Nginx IP,
   one backend worker/replica, and independent ledger/reference mounts.
2. Validate production-volume backup/restore and the rollback plan with the actual
   environment, then separately authorize real-provider and public HTTPS acceptance.

No real provider, public TLS, production data, or live deployment was accessed.
`make check-security` was not run because it accesses real configuration/key
retrieval. Existing CI/full-suite evidence was not gratuitously rerun.
No commit or push was performed during acceptance execution. This document is
being archived separately as a documentation-only change.
Local harnesses and build output remain in the
ignored test directory; temporary certificate keys must never be committed.
All five test containers and both project networks were removed; final filtered
container, network, and test-volume listings were empty. The browser task was
released. Local image caches were retained.
