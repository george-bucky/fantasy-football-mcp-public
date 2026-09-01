# Repository Guide for Agents

## Project purpose

This repository is a read-only fantasy-football decision assistant exposed through MCP. It supports
two complementary workflows:

- a credential-free manual draft path that prepares a multi-source value board before the draft and
  turns screenshot-supplied drafted players, the user's roster, and the current pick into a fast
  recommendation; and
- optional authenticated Yahoo tools for league discovery, rosters, waivers, matchups, draft state,
  and post-draft analysis.

Recommendations combine explicit league scoring and roster construction with projections, expert
consensus, ADP, structured availability, and bounded supporting evidence such as news, rookie
context, and PropLine odds. ADP is a timing signal rather than the sole ranking. News and sportsbook
markets must remain attributed, auditable context and must never be converted into fabricated
season projections.

The live manual-draft path is designed for a one-minute pick clock: slow public sources are fetched
and cached before the draft, while each recommendation uses the prepared snapshot without required
network calls. The caller supplies the complete drafted-player list and roster on every request; the
server does not perform screenshot OCR, submit picks, place wagers, or depend on hidden chat state.

## Scope and priorities

These instructions apply to the whole repository.

- Make the smallest change that solves the request. Preserve existing behavior and public MCP contracts unless the task explicitly changes them.
- Do not combine a focused fix with broad cleanup, dependency upgrades, or module consolidation.
- Inspect the current worktree before editing and preserve unrelated user changes.
- Do not commit, push, merge, deploy, or change remote resources unless the user explicitly asks.

## Coordination

- When multiple agents are available, split independent work into clearly owned, non-overlapping workstreams.
- Write plans with explicit steps and review each completed implementation step with a fresh agent before moving on.
- Keep concurrent edits isolated. Do not have multiple agents modify the same file unless ownership is handed off clearly.

## Project layout

- `fastmcp_server.py` is the FastMCP HTTP entrypoint and delegates tool calls to the legacy server.
- `fantasy_football_multi_league.py` is the stdio/legacy MCP entrypoint.
- `src/mcp_server.py` backs the installed `fantasy-football-mcp` CLI. Confirm which entrypoint is in scope before changing a tool contract.
- `src/handlers/` contains MCP tool handlers; `src/api/`, `src/services/`, `src/models/`, `src/strategies/`, and `src/agents/` contain reusable application logic.
- `src/services/manual_draft_service.py` prepares and persists the Yahoo-free board;
  `src/services/manual_draft_recommendation_service.py` applies screenshot-derived draft state to
  that cached board.
- Several root-level modules have counterparts under `src/`. Before editing one, trace the imports from the affected entrypoint. Do not assume they are interchangeable or remove duplication as incidental cleanup.
- `tests/unit/` contains mocked unit tests. `tests/integration/` covers mocked end-to-end flows. `tests/test_live_api.py` and `tests/test_real_data.py` use real Yahoo credentials or services. `tests/test_enhancement_layer.py` calls the public Sleeper API. These are not routine validation.
- `src/data/bye_weeks_2025.json` is season-specific reference data. Change it only when the task requires a season-data update.
- `.cache/manual_draft/` contains ignored prepared-board snapshots. `data/league_rosters/` contains
  optional ignored local roster records; never treat either directory as a committed source of
  truth.

## Environment and commands

Use Python 3.11; the deployment configuration and pinned requirements are aligned to it. Although package metadata declares Python 3.9 and newer, do not assume the pinned dependency set installs on older versions.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Install the project development extras when linting, formatting, or type checking is needed:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

Run the narrowest relevant check first, then expand if needed:

```bash
.venv/bin/python -m pytest tests/unit/test_<area>.py -q
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/integration -q
.venv/bin/python -m pytest tests/unit tests/integration -q
```

For code-quality checks, prefer touched files to avoid unrelated churn:

```bash
.venv/bin/python -m ruff check <files>
.venv/bin/python -m black --check <files>
.venv/bin/python -m mypy <modules>
```

Report checks that were not run and why. Do not claim live Yahoo behavior from mocked tests.

## Implementation guidance

- Preserve MCP tool names, argument schemas, response shapes, and error semantics unless a contract change is requested.
- Keep network and authentication behavior isolated from parsing, scoring, and optimization logic so normal tests remain deterministic.
- Mock Yahoo, Sleeper, Reddit, RotoWire, and other external calls in unit and integration tests. Add regression coverage for bug fixes.
- Preserve async behavior and existing fallback paths. Do not silently turn recoverable external-service failures into hard failures.
- Keep the manual recommendation hot path independent of live provider availability and under its
  five-second deadline. Refresh projections, ECR, ADP, identities, news, and odds outside the pick
  clock.
- Treat projections and league-adjusted value as the primary ranking evidence. Keep ADP as draft
  timing context, and keep news or comparable sportsbook evidence bounded and auditable.
- Surface stale sources, provider failures, unmatched players, and ambiguous identities rather than
  silently guessing or dropping them.
- Keep formatting consistent with `pyproject.toml`: Black and Ruff use a 100-character line length; mypy is configured for strict checking.
- Update user-facing docs when setup steps, environment variables, entrypoints, or MCP tool contracts change.

## Credentials and side effects

- Never commit, print, or paste values from `.env`, OAuth tokens, API secrets, local MCP client configs, or generated auth files.
- Do not run `utils/setup_yahoo_auth.py`, `utils/reauth_yahoo.py`, or `utils/refresh_yahoo_token.py` unless the user explicitly requests authentication work. These scripts can update `.env` and MCP client configuration.
- `utils/verify_setup.py` makes a real Yahoo request when an access token is configured; use it only when live setup verification is intended.
- Do not run live API scripts by default. They require credentials, make real network calls, and may generate result files.
- Treat the Yahoo integration as read-only. Do not add write actions or imply that this server can modify Yahoo leagues without an explicit, separately verified requirement.
- Use only task-owned temporary files and Docker resources. After a remotely merged PR, clean up task-owned local build artifacts, temporary files, containers, images, volumes, and networks. Never prune shared resources.

## Handoff

Summarize the root cause or goal, the minimal change made, and the validation performed. Call out any validation that still requires credentials, Yahoo approval, network access, or a live MCP client.
