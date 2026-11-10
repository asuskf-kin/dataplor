"""Correlation ID logging (org policy: every log line carries the run id)."""

import logging
import uuid
from collections.abc import MutableMapping
from typing import Any


class CorrelationAdapter(logging.LoggerAdapter[logging.Logger]):
    """Prefixes every line with the run's Correlation ID.

    main.py configures logging with a plain format, so the ID goes in the message
    instead of a custom ``%(correlation_id)s`` field that the root formatter
    would not know about.
    """

    def process(
        self, msg: object, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        correlation_id = (self.extra or {}).get("correlation_id", "-")
        return f"[cid={correlation_id}] {msg}", kwargs


AGENT_LOGGER = "cleaning_agent"


def get_logger(correlation_id: str | None = None) -> CorrelationAdapter:
    """The agent's logger bound to a Correlation ID (new UUID4 if None)."""
    return CorrelationAdapter(
        logging.getLogger(AGENT_LOGGER),
        {"correlation_id": correlation_id or str(uuid.uuid4())},
    )
