"""Hook PydanticAI into Logfire after the caller has configured."""

from __future__ import annotations

import logfire


def _caller_configured() -> bool:
    config = logfire.DEFAULT_LOGFIRE_INSTANCE.config
    return bool(getattr(config, "_initialized", False))


def instrument() -> None:
    if not _caller_configured():
        return
    logfire.instrument_pydantic_ai()
