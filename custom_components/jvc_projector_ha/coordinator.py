"""Data update coordinator for JVC Projector (2024 LAN Spec)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
import logging
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, NAME
from .jvcprojector import command, const
from .jvcprojector.error import (
    JvcProjectorAuthError,
    JvcProjectorConnectError,
    JvcProjectorError,
    JvcProjectorTimeoutError,
)
from .jvcprojector.projector import JvcProjector
from .models import supports
from .options import DEFAULT_TIMING, Timing

_LOGGER = logging.getLogger(__name__)

# Fast schedule (the Poll interval option, 10 s by default): power, input,
# signal and the picture settings shown live.
# Slow schedule: about once a minute (and whenever power, input or signal
# changes) the rarely-changing values are read too.
SLOW_PERIOD = 60  # seconds

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
    Query(const.PMNM, command.PMNM, needs_signal=True, needs_hdr=True, slow=True),
    Query(const.PMUS, command.PMUS, slow=True),
    Query(const.PMCM, command.PMCM, slow=True),
    Query(const.PMME, command.PMME, slow=True),
    Query(const.FUEM, command.FUEM, slow=True),
    # Signal details: re-read on the slow schedule and whenever input, signal,
    # picture mode or content type change.
    Query(const.IFDC, command.IFDC, needs_signal=True, slow=True),
    Query(const.IFXV, command.IFXV, needs_signal=True, slow=True),
    Query(const.IFHR, command.IFHR, needs_signal=True, slow=True),
)

# Attempts (one per minute) to read the software version if setup couldn't.
VERSION_TRIES = 3

# Values kept while the projector is off (they don't change in standby).
KEEP_WHEN_OFF = (const.IFLT, const.MODEL)


class JvcProjectorDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for JVC Projector state (2024 spec)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: JvcProjector,
        timing: Timing = DEFAULT_TIMING,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            config_entry=entry,
            logger=_LOGGER,
            name=NAME,
            update_interval=timedelta(seconds=timing.poll_interval),
        )
        self.timing = timing
        # Every Nth poll also reads the slow values (about once a minute).
        self._slow_every = max(1, round(SLOW_PERIOD / timing.poll_interval))
        # While the projector recovers from not answering, polls don't contact it.
        self._quiet_until = 0.0
        self._quiet_error: str | None = None

        self.device = device
        self.unique_id = format_mac(device.mac)

        self._poll_count = 0
        self._force_slow = False
        self._last_base: tuple[Any, ...] | None = None
        # Consecutive failures per query key, and keys already warned about.
        self._failures: dict[str, int] = {}
        self._warned: set[str] = set()
        self._version_tries = 0

        _LOGGER.debug(
            "Initialized JVC Projector coordinator for %s (%s)",
            device.host,
            self.unique_id,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch state from the projector."""
        if monotonic() < self._quiet_until:
            # Leave a projector that stopped answering alone for a while.
            if self._quiet_error is not None:
                raise UpdateFailed(self._quiet_error)
            return dict(self.data or {})
        try:
            async with asyncio.timeout(POLL_TIMEOUT):
                return await self._poll()
        except TimeoutError as err:
            self._start_quiet("Timeout polling projector")
            raise UpdateFailed("Timeout polling projector") from err
        except JvcProjectorTimeoutError as err:
            message = f"The projector stopped answering: {err}"
            self._start_quiet(message)
            raise UpdateFailed(message) from err
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
            self._poll_count % self._slow_every == 0
            or base != self._last_base
            or not prev
            or self._force_slow
        )
        self._force_slow = False
        self._poll_count += 1
        self._last_base = base

        if slow_due and not self.device.version and self._version_tries < VERSION_TRIES:
            self._version_tries += 1
            await self._read_version()
        if self.device.version:
            result[const.VERSION] = self.device.version

        if power != const.ON:
            return result

        has_signal = result.get(const.SOURCE) == const.SIGNAL
        if not has_signal:
            result[const.IFIS] = "no_signal"

        stopped = False
        for query in self._ordered_queries():
            if stopped:
                # The projector stopped answering this poll: keep the old values.
                if query.key in prev:
                    result[query.key] = prev[query.key]
                continue
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
            if not await self._query(result, query):
                # No answer: don't send it the rest of the list right away.
                stopped = True
                if query.key in prev:
                    result[query.key] = prev[query.key]

        # A new picture mode or content type can change the picture settings.
        for key in (const.PMPM, const.auto_content_type):
            if prev.get(key) != result.get(key) and prev:
                self._force_slow = True

        _LOGGER.debug("State from %s: %s", self.device.host, result)
        return result

    @property
    def failures(self) -> dict[str, int]:
        """Consecutive failures per query key (for diagnostics)."""
        return dict(self._failures)

    def _start_quiet(self, error: str | None) -> None:
        """Stop polling for the Recovery pause (if set) after no answer."""
        pause = self.timing.recovery_pause
        if pause <= 0:
            return
        self._quiet_until = monotonic() + pause
        self._quiet_error = error
        _LOGGER.info(
            "%s did not answer; pausing polling for %g s so it can recover",
            self.device.host,
            pause,
        )

    def note_command_timeout(self) -> None:
        """A command of yours got no answer: give the projector a rest too.

        Entities keep their last state (polls during the pause don't fail).
        """
        self._start_quiet(None)

    def end_quiet(self) -> None:
        """The projector answered a command: resume polling right away."""
        if self._quiet_until:
            self._quiet_until = 0.0
            self._quiet_error = None

    @property
    def quiet(self) -> bool:
        """Return True while polling is paused for recovery."""
        return monotonic() < self._quiet_until

    def _ordered_queries(self) -> list[Query]:
        """Queries for this model; ones that keep failing go last.

        A query that gets no answer ends the poll, so a command the projector
        doesn't support must not keep the ones after it from being read.
        """
        queries = self.queries()
        return sorted(
            queries,
            key=lambda q: self._failures.get(q.key, 0) >= UNSUPPORTED_AFTER,
        )

    def queries(self) -> tuple[Query, ...]:
        """Return the optional queries this model supports (projector on)."""
        model = self.device.model_code
        return tuple(q for q in QUERIES if supports(model, q.code))

    async def _read_version(self) -> None:
        """Read the software version if setup couldn't, and show it on the device."""
        version = await self.device.read_version()
        if not version:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, self.unique_id)})
        if device and device.sw_version != version:
            registry.async_update_device(device.id, sw_version=version)

    async def _query(self, result: dict[str, Any], query: Query) -> bool:
        """Run one optional query; a failure skips just that value.

        Returns False if the projector didn't answer in time.
        """
        try:
            value = await self.device.poll_ref(query.code)
        except JvcProjectorConnectError:
            raise
        except JvcProjectorError as err:
            answered = not isinstance(err, JvcProjectorTimeoutError)
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
            return answered

        if self._failures.pop(query.key, None) and query.key in self._warned:
            self._warned.discard(query.key)
            _LOGGER.info("%s (%s) is answering again", query.key, query.code)

        if value is None or value == "":
            return True
        if query.numeric:
            try:
                result[query.key] = int(value)
            except ValueError:
                _LOGGER.debug("%s not numeric: %r", query.key, value)
            return True
        result[query.key] = value
        return True

    def set_optimistic(self, **values: Any) -> None:
        """Show a value the user just set, until the next poll confirms it."""
        if self.data is None:
            return
        self._force_slow = True  # next poll re-reads everything to confirm
        self.async_set_updated_data({**self.data, **values})
