"""Shared security mode state derived from the durable Admin transition audit."""

from typing import Any


MODE_ACTIONS = (
    "LOCKDOWN_ACTIVATED",
    "LOCKDOWN_RELEASED",
    "EVACUATION_ACTIVATED",
    "EVACUATION_RELEASED",
)

_ACTION_MODE = {
    "LOCKDOWN_ACTIVATED": "LOCKDOWN",
    "LOCKDOWN_RELEASED": "NORMAL",
    "EVACUATION_ACTIVATED": "EVACUACIÓN",
    "EVACUATION_RELEASED": "NORMAL",
}


async def read_current_security_mode(pool: Any) -> dict[str, Any]:
    """Read the most recent centrally recorded mode transition.

    Returning UNKNOWN when the database is unavailable prevents a disconnected
    API from claiming that its locally simulated mode is authoritative.
    """
    if pool is None:
        return {"mode": "UNKNOWN", "action": None, "transition_id": None, "updated_at": None}
    row = await pool.fetchrow(
        """
        SELECT id, action, performed_by, timestamp
        FROM audit_logs
        WHERE action = ANY($1::text[])
        ORDER BY id DESC
        LIMIT 1
        """,
        list(MODE_ACTIONS),
    )
    if row is None:
        return {"mode": "NORMAL", "action": None, "transition_id": None, "updated_at": None}
    return {
        "mode": _ACTION_MODE[row["action"]],
        "action": row["action"],
        "transition_id": row["id"],
        "updated_at": row["timestamp"],
        "updated_by": row["performed_by"],
    }
