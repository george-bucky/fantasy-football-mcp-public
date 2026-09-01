"""Yahoo-free manual draft preparation handler."""

from typing import Any

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


__all__ = ["handle_ff_prepare_manual_draft"]
