# Weekly projection and selection contract

This is the implementation contract for the approved weekly-context work. Current source weights and initial market shrinkage/caps are explicit heuristics pending empirical evaluation, not calibrated probabilities. Historical betting archives are optional, not a rollout prerequisite.

## One assessment, separate meanings

A player assessment must expose stable identity, league scoring basis and period; raw source forecasts; effective nonzero source weights and missing-source reasons; canonical baseline expected points; each independently justified adjustment; final expected points; a separate strategy utility; confirmed eligibility constraints; and uncertainty/provenance.

Projection assessments label conditional-on-availability points explicitly; confirmed unavailability is separate and cannot become a start recommendation. Availability-aware roster summaries must not count bye/out counterfactual points.

Roster and lineup output must use the same assessment for identical inputs. The selector consumes its utility, subject to eligibility and lock rules. Raw provider forecasts remain unchanged. Existing composite_score and adjusted_projection cannot silently acquire new meanings; additive clearly named fields should describe the actual decision calculation.

## Evidence rules

- Canonical scoring must agree before blending. Unknown/custom fallback inputs cannot be treated as exact custom-league values.
- Valid zero/negative actual performances are observations, distinct from missing entries. Do not infer appearance from an absent row.
- Canonical expected points use only Yahoo/Sleeper forecasts, preserving their existing 0.50/0.30 relative weights (62.5%/37.5% when both are present), renormalized for missing sources. Recent actuals are supporting data, never fallback provider forecasts. Legacy balanced selection utility weights are 0.50/0.30/0.20. Conservative uses 0.35/0.15/0.20 plus 0.30 recent minimum; aggressive uses 0.35/0.15/0.15 plus 0.35 recent maximum. Effective weights and sparse-source limitations must be visible.
- Recent flags, usage, availability and trending effects must be individually named and tested for duplicated influence. A strategy preference is not a different raw provider forecast.
- PropLine quote lines are thresholds and probabilities, not automatically expected-stat means. A documented distribution/coverage model is required before a market mean can change points. Current paired prop prices can constrain a distribution fitted from prior actual stat observations; historical odds are not required. Compare the estimated stat mean with a genuine matching Sleeper component forecast, and translate only supported components through explicit league scoring. Apply bounded shrinkage and label the result provisional, not backtest validated. Unknown format, ambiguous identity, inferred period, stale/post-start quotes, unsupported components or incomplete pairs produce explicit limits. Anytime-TD probability is not expected touchdown count.
- Weather evidence requires exact game/venue/time and verified exposure. Observations and forecasts are different evidence. Unknown/stale coverage does not imply fair weather. Forecast normalization alone cannot create an environmental point coefficient.
- Market/weather effects must be incremental to the sources already used. Each contribution is applied once and names its validated model/version. No validated policy artifact means no claimed calibrated adjustment. A distinct performance-distribution policy may apply a provisional, bounded market estimate without claiming validation. Applying a Sleeper-relative signal to a Yahoo/Sleeper blend is an explicit approximation; do not layer the same game-environment effect twice.

## Constraints and rollout

Hard eligibility and verified locks take precedence over utility. Optimize feasible assignment jointly, with explicitly documented rounded-score tie policy; do not fill a slot with a confirmed unavailable player just because no alternate exists. Required slots should come from authoritative league configuration, with legacy inferred-slot limitations visible.

The final integrated feature defaults on after adapter/model review; lack of historical betting alone does not block it. Clearly labeled provisional market estimates are allowed; individual market/environment opt-outs and a master opt-out use the corrected baseline, never restore old bugs. Full-roster output and bounded provider budgets are required. No new MCP tool names, transactions, auth scripts, secret transfers or persistent archive grants are part of this contract.

## Freshness and historical data

Current-game odds are fetched or reused only within a bounded TTL on each recommendation; there is no claim of continuous background monitoring. Recompute adjustments from the unchanged provider baseline each time, never compound earlier deltas. Reject started games and stale quotes. For live current-week requests, actual observations from strictly earlier season/weeks may be used with their real fetch time and natural season/week sample identifiers; do not invent game IDs or timestamps or imply retrospective as-of archives. Historical simulations require separately timestamped snapshots.

## Initial current-prop model

The provisional model uses at least eight observed stat samples, empirical mid-rank quantile interpolation, and a location-shift assumption constrained by current paired fair prop probabilities. A market mean is compared with the matching genuine Sleeper component forecast; the initial shrinkage is 0.25 and the shared sum-of-absolute-component point budget is 2.0. These configurable safeguards are not fitted accuracy claims. This player-prop model is separate from the reviewed game-index/weather fallback described below. Explicit Yahoo stat modifiers are required; PPR class alone does not imply passing-TD or yardage coefficients.

`include_market_adjustments` defaults true for enhanced roster and lineup paths and can disable this layer without disabling Yahoo/Sleeper forecasts. External-disabled/Yahoo-only views remove previously attached market context before assessment.

## Game and weather fallback

When the player-prop model supplies usable corrections, game/weather layers are suppressed. Otherwise verified main full-game team totals, or a same-book total/mirror-spread pair, form a heuristic scoring-environment index compared with at least eight prior reported team scores. Only genuine Sleeper passing/rushing/receiving touchdown contributions are scaled using explicit Yahoo modifiers and 0.25 shrinkage. The betting threshold is never labeled an expected-score mean.

Weather rules require exact scheduled venue/exposure and fresh, complete NWS game-window forecasts. Whole-window sustained wind tiers 15/20/25 mph apply 0.025/0.05/0.10 volume reductions; explicitly sourced heavy rain applies 0.025. Use the strongest rule, cap weather at one point, and share a two-point absolute component budget with game TD adjustments. These transparent configurable rules are not empirically calibrated. Rain chance is not severity, and unknown exposure/roof never means fair weather.

`include_environment_adjustments` defaults true on enhanced roster/lineup paths and can be disabled independently of market adjustments. Market opt-out skips odds/history collection; weather opt-out skips registry/NWS while retaining team-history inputs if market adjustments remain enabled. Both disabled avoid the context collectors entirely. Unknown providers or source failures retain available Yahoo/Sleeper baselines. Independent game-source failures do not discard a valid weather estimate.
