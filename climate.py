"""Climate entity: one per indoor unit."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AirCloudConfigEntry
from .api import MAX_TEMP, MIN_TEMP
from .coordinator import AirCloudCoordinator
from .entity import AirCloudEntity

_LOGGER = logging.getLogger(__name__)

# Gateway mode <-> HA mode
MODE_TO_HVAC = {
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "dry": HVACMode.DRY,
    "fan": HVACMode.FAN_ONLY,
    "auto": HVACMode.HEAT_COOL,
}
HVAC_TO_MODE = {v: k for k, v in MODE_TO_HVAC.items()}

# Gateway fan <-> HA fan. The gateway offers Weak / Strong / Sharp (no auto on these units).
FAN_TO_HA = {"weak": FAN_LOW, "strong": FAN_MEDIUM, "sharp": FAN_HIGH}
HA_TO_FAN = {v: k for k, v in FAN_TO_HA.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: AirCloudConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AirCloudClimate(coordinator, dev) for dev in coordinator.data.devices.values() if dev.kind == "idu"
    )


class AirCloudClimate(AirCloudEntity, ClimateEntity):
    """Indoor unit thermostat."""

    _attr_name = None  # entity takes the device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1.0
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.DRY, HVACMode.FAN_ONLY]
    _attr_fan_modes = [FAN_LOW, FAN_MEDIUM, FAN_HIGH]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: AirCloudCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{coordinator.gateway.host}-{device.uid}-climate"

    @property
    def _state(self):
        return self.coordinator.data.idu.get(self._device.index)

    @property
    def hvac_mode(self) -> HVACMode | None:
        st = self._state
        if st is None:
            return None
        if not st.power:
            return HVACMode.OFF
        return MODE_TO_HVAC.get(st.mode or "", HVACMode.COOL)

    @property
    def hvac_action(self) -> HVACAction | None:
        st = self._state
        if st is None:
            return None
        if not st.power:
            return HVACAction.OFF
        if st.mode == "fan":
            return HVACAction.FAN
        if not st.thermo_on:
            return HVACAction.IDLE
        if st.mode == "heat":
            return HVACAction.HEATING
        if st.mode == "dry":
            return HVACAction.DRYING
        return HVACAction.COOLING

    @property
    def current_temperature(self) -> float | None:
        return self._state.room_temp if self._state else None

    @property
    def target_temperature(self) -> float | None:
        return self._state.target_temp if self._state else None

    @property
    def fan_mode(self) -> str | None:
        st = self._state
        return FAN_TO_HA.get(st.fan) if st and st.fan else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        st = self._state
        if st is None:
            return {}
        return {
            "thermo_on": st.thermo_on,
            "alarm_code": st.alarm,
            "compressor_frequency": st.compressor_freq,
            "outlet_temperature": st.outlet_temp,
            "unit_name": self.device.name,
            "capacity": st.capacity,
        }

    # -- commands -------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_idu(self._device.index, power=False)
            return
        await self.coordinator.async_set_idu(self._device.index, power=True, mode=HVAC_TO_MODE[hvac_mode])

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        changes: dict[str, Any] = {}
        if temp is not None:
            changes["target_temp"] = float(temp)
        if (mode := kwargs.get("hvac_mode")) is not None:
            if mode == HVACMode.OFF:
                changes["power"] = False
            else:
                changes["power"] = True
                changes["mode"] = HVAC_TO_MODE[mode]
        if changes:
            await self.coordinator.async_set_idu(self._device.index, **changes)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.async_set_idu(self._device.index, fan=HA_TO_FAN[fan_mode])

    async def async_turn_on(self) -> None:
        await self.coordinator.async_set_idu(self._device.index, power=True)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_set_idu(self._device.index, power=False)
