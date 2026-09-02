"""Sensors for indoor and outdoor units."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfFrequency, UnitOfPressure, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AirCloudConfigEntry
from .api import IduState, OduState
from .entity import AirCloudEntity


@dataclass(frozen=True, kw_only=True)
class AirCloudSensorDescription(SensorEntityDescription):
    value_fn: Callable[[IduState | OduState], float | int | str | None]


IDU_SENSORS: tuple[AirCloudSensorDescription, ...] = (
    AirCloudSensorDescription(
        key="room_temperature",
        translation_key="room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda s: s.room_temp,
    ),
    AirCloudSensorDescription(
        key="outlet_temperature",
        translation_key="outlet_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.outlet_temp,
    ),
    AirCloudSensorDescription(
        key="coil_liquid_temperature",
        translation_key="coil_liquid_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.coil_liquid_temp,
    ),
    AirCloudSensorDescription(
        key="coil_gas_temperature",
        translation_key="coil_gas_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.coil_gas_temp,
    ),
    AirCloudSensorDescription(
        key="compressor_frequency",
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.compressor_freq,
    ),
    AirCloudSensorDescription(
        key="alarm_code",
        translation_key="alarm_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.alarm,
    ),
)

ODU_SENSORS: tuple[AirCloudSensorDescription, ...] = (
    AirCloudSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=lambda s: s.ambient_temp,
    ),
    AirCloudSensorDescription(
        key="discharge_temperature",
        translation_key="discharge_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.discharge_temp,
    ),
    AirCloudSensorDescription(
        key="discharge_pressure",
        translation_key="discharge_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: None if s.discharge_pressure is None else s.discharge_pressure * 10,  # MPa -> bar
    ),
    AirCloudSensorDescription(
        key="suction_pressure",
        translation_key="suction_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPressure.BAR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: None if s.suction_pressure is None else s.suction_pressure * 10,
    ),
    AirCloudSensorDescription(
        key="compressor_frequency",
        translation_key="compressor_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        value_fn=lambda s: s.compressor_freq,
    ),
    AirCloudSensorDescription(
        key="fan_power",
        translation_key="fan_power",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.fan_power,
    ),
    AirCloudSensorDescription(
        key="cycle",
        translation_key="cycle",
        value_fn=lambda s: s.cycle or None,
    ),
    AirCloudSensorDescription(
        key="alarm_code",
        translation_key="alarm_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.alarm,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AirCloudConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[AirCloudSensor] = []
    for dev in coordinator.data.devices.values():
        descs = IDU_SENSORS if dev.kind == "idu" else ODU_SENSORS
        entities.extend(AirCloudSensor(coordinator, dev, d) for d in descs)
    async_add_entities(entities)


class AirCloudSensor(AirCloudEntity, SensorEntity):
    entity_description: AirCloudSensorDescription

    def __init__(self, coordinator, device, description: AirCloudSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gateway.host}-{device.uid}-{description.key}"

    @property
    def native_value(self):
        data = self.coordinator.data
        st = data.idu.get(self._device.index) if self._device.kind == "idu" else data.odu.get(self._device.index)
        if st is None:
            return None
        return self.entity_description.value_fn(st)
