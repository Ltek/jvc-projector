"""Data update coordinator for JVC Projector (2024 LAN Spec)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import NAME
from .jvcprojector import command, const
from .jvcprojector.error import (
    JvcProjectorAuthError,
    JvcProjectorConnectError,
    JvcProjectorError,
)
from .jvcprojector.projector import JvcProjector

_LOGGER = logging.getLogger(__name__)

# Fast schedule: power, input, signal and the picture settings shown live.
UPDATE_INTERVAL = timedelta(seconds=10)

# Slow schedule: every Nth fast poll (and whenever power, input or signal
# changes) the rarely-changing values are read too.
SLOW_EVERY = 6  # x 10 s = 1 minute

# Upper bound for one whole poll, so a wedged projector can't stall HA.
POLL_TIMEOUT = 45  # seconds

# A query that fails this many polls in a row is retried only on the slow
# schedule, so an unsupported command doesn't cost a timeout every 10 s.
UNSUPPORTED_AFTER = 3


@dataclass(frozen=True)
class Query:
    """One optional status query."""

    key: str
    code: str
    needs_signal: bool = False
    needs_hdr: bool = False
    slow: bool = False
    numeric: bool = False


# Queried only while the projector is on.
QUERIES: tuple[Query, ...] = (
    Query(const.PMPM, command.PMPM),
    Query(const.PMDC, command.PMDC),
    Query(const.PMCV, command.PMCV, numeric=True),
    Query(const.IFIS, command.IFIS, needs_signal=True),
    Query(const.auto_content_type, command.PMAT, needs_signal=True),
    Query(const.IFCM, command.IFCM, needs_signal=True, slow=True),
    Query(const.IFIN, command.IFIN, slow=True),
    Query(const.IFLT, command.IFLT, slow=True, numeric=True),
    # Installation / picture settings: they change only when someone changes
    # them (set from HA, they update at once), so the slow schedule is enough.
    Query(const.INML, command.INML, slow=True),
    Query(const.INVS, command.INVS, slow=True),
    Query(const.PMLL, command.PMLL, slow=True),
    Query(const.PMHP, command.PMHP, needs_signal=True, needs_hdr=True, slow=True),
    Query(const.PMHL, command.PMHL, needs_signal=True, needs_hdr=True, slow=True),
)

# Values kept while the projector is off (they don't change in standby).
KEEP_WHEN_OFF = (const.IFLT, const.MODEL)


class JvcProjectorDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for JVC Projector state (2024 spec)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device: JvcProjector
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            config_entry=entry,
            logger=_LOGGER,
            name=NAME,
            update_interval=UPDATE_INTERVAL,
        )

        self.device = device
        self.unique_id = format_mac(device.mac)

        self._poll_count = 0
        self._force_slow = False
        self._last_base: tuple[Any, ...] | None = None
        # Consecutive failures per query key, and keys already warned about.
        self._failures: dict[str, int] = {}
        self._warned: set[str] = set()

        _LOGGER.debug(
            "Initialized JVC Projector coordinator for %s (%s)",
            device.host,
            self.unique_id,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch state from the projector."""
        try:
            async with asyncio.timeout(POLL_TIMEOUT):
                return await self._poll()
        except TimeoutError as err:
            raise UpdateFailed("Timeout polling projector") from err
        except JvcProjectorAuthError as err:
            raise ConfigEntryAuthFailed("Password authentication failed") from err
        except JvcProjectorError as err:
            raise UpdateFailed(f"Error polling projector: {err}") from err

    async def _poll(self) -> dict[str, Any]:
        """Run one poll: base state, then the optional queries."""
        prev = self.data or {}
        state = await self.device.get_state()
        result: dict[str, Any] = {k: v for k, v in state.items() if v is not None}

        for key in KEEP_WHEN_OFF:
            if key in prev:
                result[key] = prev[key]

        # Model is read once at setup (MD) and never changes.
        if const.MODEL not in result and self.device.model_code:
            result[const.MODEL] = self.device.model_code

        power = result.get(const.POWER)
        base = (power, result.get(const.INPUT), result.get(const.SOURCE))
        slow_due = (
            self._poll_count % SLOW_EVERY == 0
            or base != self._last_base
            or not prev
            or self._force_slow
        )
        self._force_slow = False
        self._poll_count += 1
        self._last_base = base

        if power != const.ON:
            return result

        has_signal = result.get(const.SOURCE) == const.SIGNAL
        if not has_signal:
            result[const.IFIS] = "no_signal"

        for query in self.queries():
            if query.needs_signal and not has_signal:
                continue
            if (
                query.needs_hdr
                and result.get(const.auto_content_type) not in const.HDR_CONTENT
            ):
                continue
            unsupported = self._failures.get(query.key, 0) >= UNSUPPORTED_AFTER
            if (query.slow or unsupported) and not slow_due:
                if query.key in prev:
                    result[query.key] = prev[query.key]
                continue
            await self._query(result, query)

        # A new picture mode or content type can change the picture settings.
        for key in (const.PMPM, const.auto_content_type):
            if prev.get(key) != result.get(key) and prev:
                self._force_slow = True

        _LOGGER.debug("State from %s: %s", self.device.host, result)
        return result

    def queries(self) -> tuple[Query, ...]:
        """Return the optional queries for a powered-on projector."""
        return QUERIES

    async def _query(self, result: dict[str, Any], query: Query) -> None:
        """Run one optional query; a failure skips just that value."""
        try:
            value = await self.device.poll_ref(query.code)
        except JvcProjectorConnectError:
            raise
        except JvcProjectorError as err:
            count = self._failures.get(query.key, 0) + 1
            self._failures[query.key] = count
            # Warn once per key until it works again; the rest goes to debug.
            if count == UNSUPPORTED_AFTER and query.key not in self._warned:
                self._warned.add(query.key)
                _LOGGER.warning(
                    "%s (%s) has failed %d polls in a row (%s); now retrying "
                    "once a minute",
                    query.key,
                    query.code,
                    count,
                    err,
                )
            else:
                _LOGGER.debug("%s (%s) failed: %s", query.key, query.code, err)
            return

        if self._failures.pop(query.key, None) and query.key in self._warned:
            self._warned.discard(query.key)
            _LOGGER.info("%s (%s) is answering again", query.key, query.code)

        if value is None or value == "":
            return
        if query.numeric:
            try:
                result[query.key] = int(value)
            except ValueError:
                _LOGGER.debug("%s not numeric: %r", query.key, value)
            return
        result[query.key] = value

    def set_optimistic(self, **values: Any) -> None:
        """Show a value the user just set, until the next poll confirms it."""
        if self.data is None:
            return
        self._force_slow = True  # next poll re-reads everything to confirm
        self.async_set_updated_data({**self.data, **values})
