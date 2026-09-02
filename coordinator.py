"""DataUpdateCoordinator for the airCloud Gateway."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AirCloudAuthError,
    AirCloudConnectionError,
    AirCloudError,
    AirCloudGateway,
    Device,
    IduState,
    OduState,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class GatewayData:
    """Everything the entities need, refreshed every poll."""

    devices: dict[str, Device] = field(default_factory=dict)  # uid -> Device
    idu: dict[int, IduState] = field(default_factory=dict)  # index -> state
    odu: dict[int, OduState] = field(default_factory=dict)  # index -> state


class AirCloudCoordinator(DataUpdateCoordinator[GatewayData]):
    """Polls every unit on the gateway."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        gateway: AirCloudGateway,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {gateway.host}",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=entry,
        )
        self.gateway = gateway
        self._devices: dict[str, Device] = {}
        self._device_refresh_counter = 0

    async def _async_setup(self) -> None:
        """Load the device list once at startup."""
        try:
            devices = await self.gateway.async_get_devices()
        except AirCloudAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AirCloudError as err:
            raise UpdateFailed(str(err)) from err
        self._devices = {d.uid: d for d in devices}

    async def _async_update_data(self) -> GatewayData:
        # Re-read the device list every ~40 polls so renamed units get picked up.
        self._device_refresh_counter += 1
        if not self._devices or self._device_refresh_counter >= 40:
            self._device_refresh_counter = 0
            try:
                self._devices = {d.uid: d for d in await self.gateway.async_get_devices()}
            except AirCloudAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except AirCloudError as err:
                if not self._devices:
                    raise UpdateFailed(str(err)) from err
                _LOGGER.debug("Device list refresh failed, keeping cached list: %s", err)

        data = GatewayData(devices=dict(self._devices))
        try:
            # Requests are serialised inside the client (the gateway is a tiny CGI server),
            # so we just fire them all and let the lock pace them.
            for dev in self._devices.values():
                if dev.kind == "idu":
                    data.idu[dev.index] = await self.gateway.async_get_idu_status(dev.index)
                else:
                    data.odu[dev.index] = await self.gateway.async_get_odu_status(dev.index)
        except AirCloudAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (AirCloudConnectionError, AirCloudError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"Error polling gateway: {err}") from err
        return data

    # -- write helpers --------------------------------------------------------

    async def async_set_idu(self, index: int, **changes) -> None:
        """Merge `changes` into the current state and push the full form."""
        current = self.data.idu.get(index) if self.data else None
        power = changes.get("power", current.power if current else False)
        mode = changes.get("mode", (current.mode if current and current.mode else "cool"))
        fan = changes.get("fan", (current.fan if current and current.fan in ("weak", "strong", "sharp") else "sharp"))
        target = changes.get("target_temp", (current.target_temp if current and current.target_temp else 24.0))
        try:
            await self.gateway.async_set_idu(index, power=power, mode=mode, fan=fan, target_temp=target)
        except AirCloudAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AirCloudError as err:
            raise UpdateFailed(str(err)) from err
        # The H-Link bus takes a moment to reflect the change; give it a second, then refresh.
        await asyncio.sleep(1.5)
        await self.async_request_refresh()
