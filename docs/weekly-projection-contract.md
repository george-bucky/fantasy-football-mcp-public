# Weekly projection and selection contract

This is the implementation contract for the approved weekly-context work. The canonical weekly forecast source is Sleeper. Strategy utility weights and initial market shrinkage/caps are explicit heuristics pending empirical evaluation, not calibrated probabilities. Historical betting archives are optional, not a rollout prerequisite.

## One assessment, separate meanings

A player assessment must expose stable identity, league scoring basis and period; raw source forecasts; effective nonzero source weights and missing-source reasons; canonical baseline expected points; each independently justified adjustment; final expected points; a separate strategy utility; confirmed eligibility constraints; and uncertainty/provenance.

Projection assessments label conditional-on-availability points explicitly; confirmed unavailability is separate and cannot become a start recommendation. Availability-aware roster summaries must not count bye/out counterfactual points.

Roster and lineup output must use the same assessment for identical inputs. The selector consumes its utility, subject to eligibility and lock rules. Raw provider forecasts remain unchanged. Existing composite_score and adjusted_projection cannot silently acquire new meanings; additive clearly named fields should describe the actual decision calculation.

The calculation order is: genuine Sleeper baseline → accepted bounded Vegas/market
and weather adjustments → strategy blend of the resulting final expected points
with supported recent actuals → health/role multipliers on that utility → eligibility
and lock constraints plus global lineup assignment. Raw provider values, canonical
baseline points, and final expected points are independent of strategy. Strategy
changes selection utility, not the provider forecast or the context-adjusted points.
Context deltas enter the final forecast once; they are not added as an unweighted
bonus after the strategy blend or reapplied after health/role factors.

## Evidence rules

- A genuine Sleeper forecast must match the exact player, season/week, and supported scoring class (`standard`, `half_ppr`, or `ppr`). This is scoring-class compatibility, not a claim to reproduce every Yahoo custom modifier or bonus. Unsupported custom scoring (`fallback_custom_ppr`) omits incompatible Sleeper/PPR inputs. Unresolved league scoring may retain the existing `fallback_default_ppr` forecast, explicitly labeled provisional with scoring basis `unknown`; it is not a verified custom-league forecast. Market/weather scoring gates remain separate.
- Valid zero/negative actual performances are observations, distinct from missing entries. Do not infer appearance from an absent row.
- Canonical baseline expected points use only a genuine, compatible Sleeper forecast with effective weight 1.0. Yahoo raw fields and optional observed Yahoo projection snapshots are comparison-only; they receive no baseline or strategy-utility weight. If Sleeper is missing, stale, invalid, or incompatible, the baseline remains unavailable: neither Yahoo values nor recent actuals substitute for it.
- Strategy utility applies the remapped projection weight to final expected points, after accepted market/weather corrections: balanced uses 0.80 final expected points / 0.20 recent average; conservative uses 0.50 final expected points / 0.20 recent average / 0.30 recent minimum; aggressive uses 0.50 final expected points / 0.15 recent average / 0.35 recent maximum. Normalize over the available supported inputs; if historical inputs are absent, the projection's effective utility weight is 1.0. A missing forecast remains unavailable even when historical actuals exist. Effective weights and sparse-source limitations must be visible. Historical actuals remain utility inputs, not fallback provider forecasts.
- Recent flags, usage, availability and trending effects must be individually named and tested for duplicated influence. A strategy preference is not a different raw provider forecast.
- PropLine quote lines are thresholds and probabilities, not automatically expected-stat means. A documented distribution/coverage model is required before a market mean can change points. Current paired prop prices can constrain a distribution fitted from prior actual stat observations; historical odds are not required. Compare the estimated stat mean with a genuine matching Sleeper component forecast, and translate only supported components through explicit league scoring. Apply bounded shrinkage and label the result provisional, not backtest validated. Unknown format, ambiguous identity, inferred period, stale/post-start quotes, unsupported components or incomplete pairs produce explicit limits. Anytime-TD probability is not expected touchdown count.
- Weather evidence requires exact game/venue/time and verified exposure. Observations and forecasts are different evidence. Unknown/stale coverage does not imply fair weather. Forecast normalization alone cannot create an environmental point coefficient.
- Market/weather effects must be incremental to the sources already used. Each contribution is applied once and names its validated model/version. No validated policy artifact means no claimed calibrated adjustment. A distinct performance-distribution policy may apply a provisional, bounded market estimate without claiming validation. The modeled signal is relative to the matching Sleeper forecast; do not layer the same game-environment effect twice.

## Strategy example

A genuine Sleeper baseline of 10 points plus an accepted bounded context delta of
+2 yields final expected points of 12 for every strategy. With a recent average
of 15, balanced base utility is `0.80 * 12 + 0.20 * 15 = 12.6`, before health/role
multipliers and eligibility/lock constraints. If no supported historical inputs
are available, the final forecast carries effective utility weight 1.0. None of
these steps supplies estimated points when the genuine baseline is missing.

## Constraints and rollout

Hard eligibility and verified locks take precedence over utility. Optimize feasible assignment jointly, with explicitly documented rounded-score tie policy; do not fill a slot with a confirmed unavailable player just because no alternate exists. Required slots should come from authoritative league configuration, with legacy inferred-slot limitations visible.

The final integrated feature defaults on after adapter/model review; lack of historical betting alone does not block it. Clearly labeled provisional market estimates are allowed; individual market/environment opt-outs and a master opt-out use the corrected baseline, never restore old bugs. Full-roster output and bounded provider budgets are required. No new MCP tool names, transactions, auth scripts, secret transfers or persistent archive grants are part of this contract.

## Freshness and historical data

Current-game odds are fetched or reused only within a bounded TTL on each recommendation; there is no claim of continuous background monitoring. Recompute adjustments from the unchanged provider baseline each time, never compound earlier deltas. Reject started games and stale quotes. For live current-week requests, actual observations from strictly earlier season/weeks may be used with their real fetch time and natural season/week sample identifiers; do not invent game IDs or timestamps or imply retrospective as-of archives. Historical simulations require separately timestamped snapshots.

## Initial current-prop model

The provisional model uses at least eight observed stat samples, empirical mid-rank quantile interpolation, and a location-shift assumption constrained by current paired fair prop probabilities. A market mean is compared with the matching genuine Sleeper component forecast; the initial shrinkage is 0.25 and the shared sum-of-absolute-component point budget is 2.0. These configurable safeguards are not fitted accuracy claims. This player-prop model is separate from the reviewed game-index/weather fallback described below. Explicit Yahoo stat modifiers are required; PPR class alone does not imply passing-TD or yardage coefficients.

`include_market_adjustments` defaults true for enhanced roster and lineup paths and can disable this layer without disabling the Sleeper baseline. External-disabled/basic views remove previously attached market context before assessment; Yahoo comparison values do not become a fallback baseline.

## Game and weather fallback

When the player-prop model supplies usable corrections, game/weather layers are suppressed. Otherwise verified main full-game team totals, or a same-book total/mirror-spread pair, form a heuristic scoring-environment index compared with at least eight prior reported team scores. Only genuine Sleeper passing/rushing/receiving touchdown contributions are scaled using explicit Yahoo modifiers and 0.25 shrinkage. The betting threshold is never labeled an expected-score mean.

Weather rules require exact scheduled venue/exposure and fresh, complete NWS game-window forecasts. Whole-window sustained wind tiers 15/20/25 mph apply 0.025/0.05/0.10 volume reductions; explicitly sourced heavy rain applies 0.025. Use the strongest rule, cap weather at one point, and share a two-point absolute component budget with game TD adjustments. These transparent configurable rules are not empirically calibrated. Rain chance is not severity, and unknown exposure/roof never means fair weather.

`include_environment_adjustments` defaults true on enhanced roster/lineup paths and can be disabled independently of market adjustments. Market opt-out skips odds/history collection; weather opt-out skips registry/NWS while retaining team-history inputs if market adjustments remain enabled. Both disabled avoid the context collectors entirely. Context-provider failures retain a valid Sleeper baseline; failure of the Sleeper forecast itself leaves no canonical baseline. Independent game-source failures do not discard a valid weather estimate.

The weekly odds collector requests DraftKings and FanDuel main lines only, with explicit partial-coverage provenance. This keeps response and result bounds intact; these two books are not assumed independent. The general odds tool retains its default all-line behavior. Provider failures and unmatched identities remain visible.

## Optional observed Yahoo forecasts

The verified Yahoo roster API response does not supply individual player forecasts.

`ff_get_roster` (projection-enabled views) and `ff_build_lineup` accept an optional
`yahoo_projection_snapshot` object. This is a caller-provided observation of Yahoo's
visible **Proj Pts** column, not an automated forecast API or browser fetch. The
caller must verify the league, team, week, season and scoring settings. Do not use
actual `player_points` values as projections or supply cookies, tokens or browser storage.

The object requires `source_kind: "yahoo_visible_projection_snapshot"`, the plain
HTTPS Yahoo team `source_url` (`https://football.fantasysports.yahoo.com/f1/{leagueid}/{teamid}`,
without a query), `season`, `week`, `scoring_basis`, an aware ISO `observed_at`, and
`rows: [{"player_id": "1001", "projection": 15.5}]`. Each row can instead use the
full scoped Yahoo `player_key`. Observations expire after 900 seconds. Exact roster
IDs are required; names and NFL team abbreviations cannot identify a defense.

The response exposes `yahoo_projection_snapshot_audit`. Invalid or stale snapshots
leave provider values intact and include a reason; valid unrostered rows are skipped
and counted. Explicit finite zero and negative forecasts are valid. Assessment
provenance distinguishes observation time from the server assessment clock, labels
the source caller-provided and not server-refetched, and preserves the original API
value separately. Both raw Yahoo values and valid snapshots remain comparison-only: they
never enter baseline expected points or strategy utility. Missing snapshots do not affect
a valid Sleeper forecast, and snapshots cannot replace a missing Sleeper forecast.
Basic/projections-disabled roster views do not consume the snapshot. No snapshot is persisted by this bridge.

## Provider roles and operational limits

Yahoo remains authoritative for league scoring configuration/class, roster membership,
selected positions and eligibility, and reported actual player points. Its roster API
actuals are not individual forecasts. Optional visible Yahoo forecasts are for comparison
only, including when their scoring or observation provenance is valid.

The Sleeper weekly projection endpoint is undocumented and may change or become
unavailable independently of Sleeper's documented public API. Validate its payload and
provenance on every refresh, surface failures explicitly, and do not silently replace
missing forecasts with rankings, Yahoo values, or historical performance. The manual
draft workflow and the market/weather model rules above are unchanged.
