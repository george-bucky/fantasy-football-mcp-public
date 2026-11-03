# Cloud stdio runtime

These scripts prepare the repository's root stdio MCP runtime. Current `main`
already includes the weekly projection work and the 23-tool checker contract.
The runtime adds no tool names or HTTP listener. The installed
`fantasy-football-mcp` command targets a separate implementation; use the launcher
below for the root server.

This is source and synthetic-test preparation, not a deployed cloud environment.
No credentials, cloud configuration, durable storage, or private league data are
provisioned by these scripts.

## Setup and local verification

Start from the reviewed repository revision with Python 3.11 available:

```sh
bash scripts/cloud_setup.sh
.venv/bin/python scripts/cloud_mcp.py --check
.venv/bin/python scripts/cloud_mcp.py --config
```

Setup creates or reuses this checkout's Python 3.11 `.venv`, installs pinned
`requirements.txt` from public PyPI with pip's isolated mode, and runs the local
stdio contract check. Existing environments with another Python version and
symlink `.venv` directories are rejected without replacement. Normal virtualenv
interpreter symlinks are supported.

`--check` initializes the actual root stdio server and lists its 23 tools with
provider credentials/store access removed and provider network calls disabled.
It does not verify Yahoo access, league/roster retrieval, forecasts, markets,
weather, or persistence across cloud sessions. Do not substitute the full
`utils/verify_setup.py` command: that checker can make a real Yahoo request.

`--config` prints a non-mutating MCP registration preview containing absolute
paths and environment-variable names, never credential values. Review and adapt
it for the selected cloud environment. No MCP registration is written. The
launcher starts `fantasy_football_multi_league.py` through stdio and sets
`FANTASY_CLOUD_RUNTIME=1` so that this launch does not load the repository `.env`.
Use the reviewed launcher path in the preview, not `fastmcp_server.py`.

## Provider roles and outbound access

Bind only approved credentials through the selected environment's secret
mechanism. The config preview lists names that may be forwarded; it does not
create, copy, or prove the readiness of any secret.

| Purpose | Hosts / credentials |
| --- | --- |
| Dependency installation | `pypi.org`, `files.pythonhosted.org`; no provider credentials |
| Yahoo league settings, rosters, eligibility and actual points | `fantasysports.yahooapis.com`; `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, and access/refresh tokens; `YAHOO_GUID` is optional context |
| Yahoo OAuth refresh | `api.login.yahoo.com`; credential use and refresh testing require the approved setup step below |
| Sleeper weekly forecasts, identities and recent actuals | `api.sleeper.app`; public endpoints, with an undocumented weekly projection endpoint that can fail independently |
| PropLine sportsbook context | `api.prop-line.com`; `PROPLINE_API_KEY` |
| Reddit sentiment | `www.reddit.com`, `oauth.reddit.com` via PRAW; optional `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME` |
| ESPN news and preseason data | `site.api.espn.com`, `lm-api-reads.fantasy.espn.com`; public |
| RotoWire NFL RSS | `www.rotowire.com`; public |
| ADP | `fantasyfootballcalculator.com`; public |
| ECR, schedules and venue registry | `raw.githubusercontent.com`; public |
| nflverse release data | `github.com`, `release-assets.githubusercontent.com`; allow the verified release redirect host |
| NWS game-window forecasts | `api.weather.gov`; public |

Yahoo is league/state data; the weekly canonical player forecast is genuine
compatible Sleeper data. Optional Yahoo visible-projection observations remain
comparison-only. PropLine and verified weather inputs can supply the existing
bounded modeled corrections. This runtime does not change those model rules.
Optional services remain unavailable when their credentials or sources are
missing; the contract check does not establish live provider health.

These are the fantasy server's integrations. Other workstation MCP registrations,
desktop browser sessions, and local binary paths are not migrated by this setup.
Review required hosts, redirects and public package-download access in the cloud
network policy; do not broaden access merely to mask a provider failure.

## Token persistence requires an approved durable backend

`YAHOO_TOKEN_STORE` is opt-in and names an absolute path to an **already
provisioned** private JSON file. This implementation uses a POSIX filesystem
with atomic replacement and `flock`; it is not a distributed secret manager.
It never creates the parent directory or seeds the token file from environment
variables. The version-1 schema, using synthetic examples only, is:

```json
{"version": 1, "access_token": "SYNTHETIC_EXAMPLE", "refresh_token": "SYNTHETIC_EXAMPLE"}
```

The file must be owned by the runtime user with mode 0600, its parent must be
owned and private (0700), and paths must satisfy the store's ownership and
symlink checks. Refresh creates a private sibling lock file, rereads current
stored tokens under its lock, and atomically persists the resulting pair before
publishing it to the process. Invalid explicitly configured stores fail closed.
Read-only startup does not initialize a missing store. A storage failure after
provider-side rotation cannot roll back Yahoo's rotation and may require recovery
or reauthorization.

Once a refresh starts under the lock, caller cancellation waits for that bounded
HTTP attempt (60-second timeout) to finish saving/publishing its result before
releasing the lock and reporting cancellation. Cancellation while waiting for a
lock remains immediate. This does not protect against abrupt process termination
or uncertain provider-side rotation after a network failure. Valid rotated tokens
are retained even when optional expiry metadata is invalid; expiry is then reported
as unknown.

Start with one runtime group sharing one compatible, genuinely durable volume.
Filesystem locks do not coordinate independent cloud disks or copied secret
snapshots. Environment-injected tokens are not automatically written back to
an environment's secret manager by this file-store implementation.

**Fresh Codex cloud workspaces need a separately approved durable backend.**
The repository, its checkout-local `.tokens` or caches, and an ephemeral runtime
disk are not a persistence plan. If the selected environment cannot expose a
suitable durable POSIX volume, choose and review a different durable backend and
adapter before enabling authentication/rotation there. This PR does not grant
that access or claim that any Codex environment supplies such a volume.

## Private roster and draft state

Manual-draft snapshots default to repo-relative `.cache/manual_draft`; generic
`CACHE_DIR` does not relocate them. Saved league context and provider policy live
under `data/league_rosters`. Both contain private session context and are excluded
from Git and image uploads, along with `.env`, `.tokens`, and local orchestration
notes. Keep any actual durable token store outside the checkout and image context.
Ignore rules are safeguards, not permission to upload arbitrary private files.

After approval for an exact destination, restore or mount only the selected
boards/rosters/history, preserve private permissions and complete snapshot
checksums, and distinguish saved membership from current live starters or moves.
Ordinary response caches can be rebuilt. No private-state migration is automatic.

## Sequential activation and acceptance

1. Choose the named cloud environment, reviewed source revision, runtime/MCP
   registration, outbound policy, and provider scope. Select the durable backend
   and its runtime access model before token use. Review/apply those configurations
   through their normal approval workflow; this source PR does not apply them.
2. Confirm each credential transfer separately: Yahoo app/tokens, PropLine, and
   any Reddit credentials. Separately confirm the durable-store destination,
   access grant, and initial seeding through an approved secret-handling mechanism.
   Confirm any private board/roster upload and destination separately.
3. Authorize the Yahoo refresh test before running it. Then validate read-only
   provider access and actual league/roster retrieval, restart in a fresh cloud
   session, and verify that it loads the latest durable token pair. Check genuine
   Sleeper forecasts and any enabled market/weather inputs with their provenance
   and failure statuses. Contract checking alone proves none of this acceptance.

Do not copy secrets into source, documents, logs, previews, or image layers.
No OAuth login, real refresh, storage grant, private-state upload, HTTP exposure,
or production transaction is part of the synthetic preparation. An HTTP deployment
would need its own authentication and access-control review.
