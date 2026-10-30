from typing import Optional

from nemoguardrails.actions import action
from nemoguardrails.actions.rail_outcome import RailOutcome


@action(is_system_action=True)
async def validate_code_input(context: Optional[dict] = None):
    """Allow source code while rejecting unexpectedly oversized requests."""
    context = context or {}
    message = context.get("last_user_message") or ""
    if not isinstance(message, str):
        message = str(message)

    if len(message) > 45000:
        return RailOutcome.block(
            reason="Input is too long. Shorten the code or compiler error and try again."
        )

    return RailOutcome.allow()
