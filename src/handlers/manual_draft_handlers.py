"""Yahoo-free manual draft preparation handler."""

from typing import Any

from src.services.manual_draft_recommendation_service import (
    manual_draft_recommendation_service,
)
from src.services.manual_draft_service import manual_draft_service


async def handle_ff_prepare_manual_draft(arguments: dict[str, Any]) -> dict[str, Any]:
    """Prepare a reusable offline value board from an explicit league profile."""

    profile = arguments.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("profile must be an object")
    return await manual_draft_service.prepare(
        profile=profile,
        preview_limit=arguments.get("preview_limit", 25),
        force_refresh=arguments.get("force_refresh", False),
    )


async def handle_ff_get_manual_draft_recommendation(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Recommend a manual pick from a persisted board and complete supplied state."""

    prepared_id = arguments.get("prepared_id")
    current_overall_pick = arguments.get("current_overall_pick")
    drafted_players = arguments.get("drafted_players")
    roster = arguments.get("roster")
    optional_evidence = arguments.get("optional_evidence", [])
    if not isinstance(prepared_id, str):
        raise ValueError("prepared_id must be a string")
    if isinstance(current_overall_pick, bool) or not isinstance(current_overall_pick, int):
        raise ValueError("current_overall_pick must be an integer")
    if not isinstance(drafted_players, list):
        raise ValueError("drafted_players must be an array")
    if not isinstance(roster, list):
        raise ValueError("roster must be an array")
    if not isinstance(optional_evidence, list):
        raise ValueError("optional_evidence must be an array")
    return await manual_draft_recommendation_service.recommend(
        prepared_id=prepared_id,
        current_overall_pick=current_overall_pick,
        drafted_players=drafted_players,
        roster=roster,
        optional_evidence=optional_evidence,
        alternative_count=arguments.get("alternative_count", 4),
    )


__all__ = [
    "handle_ff_get_manual_draft_recommendation",
    "handle_ff_prepare_manual_draft",
]
