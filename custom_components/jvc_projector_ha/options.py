"""User-adjustable timing.

Settings → Devices & services → JVC Projector → Configure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Option key -> (default, minimum, maximum), in seconds.
POLL_INTERVAL = "poll_interval"
RESPONSE_TIMEOUT = "response_timeout"
CHANGE_TIMEOUT = "change_timeout"
LENS_TIMEOUT = "lens_timeout"
RECOVERY_PAUSE = "recovery_pause"

LIMITS: dict[str, tuple[float, float, float]] = {
    # How often the projector is asked for its state.
    POLL_INTERVAL: (10, 5, 120),
    # How long to wait for an answer to a query or a quick command.
    RESPONSE_TIMEOUT: (5, 1, 30),
    # Picture mode and input changes: the projector answers only once the change
    # is done (pyjvcprojector allows 10 s for these).
    CHANGE_TIMEOUT: (10, 2, 60),
    # Lens memory: the projector answers once the lens has stopped moving.
    LENS_TIMEOUT: (30, 5, 120),
    # After the projector stops answering, leave it alone this long before
    # polling again (0 = no pause). Your own commands are still sent.
    RECOVERY_PAUSE: (30, 0, 600),
}


@dataclass(frozen=True)
class Timing:
    """The timing options for one config entry, with defaults filled in."""

    poll_interval: float
    response_timeout: float
    change_timeout: float
    lens_timeout: float
    recovery_pause: float

    @classmethod
    def from_options(cls, options: Mapping[str, Any] | None) -> Timing:
        """Read options, falling back to defaults and clamping to the limits."""
        options = options or {}
        values: dict[str, float] = {}
        for key, (default, low, high) in LIMITS.items():
            try:
                value = float(options.get(key, default))
            except (TypeError, ValueError):
                value = default
            values[key] = min(high, max(low, value))
        return cls(**values)


DEFAULT_TIMING = Timing.from_options(None)
