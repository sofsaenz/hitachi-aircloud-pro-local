"""Binary sensors: thermo-on (compressor demand) and alarm per unit."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AirCloudConfigEntry
from .entity import AirCloudEntity

IDU_THERMO = BinarySensorEntityDescription(
    key="thermo_on",
    translation_key="thermo_on",
    device_class=BinarySensorDeviceClass.RUNNING,
    entity_category=EntityCategory.DIAGNOSTIC,
)
ALARM = BinarySensorEntityDescription(
    key="alarm",
    translation_key="alarm",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: AirCloudConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[AirCloudBinarySensor] = []
    for dev in coordinator.data.devices.values():
        entities.append(AirCloudBinarySensor(coordinator, dev, ALARM))
        if dev.kind == "idu":
            entities.append(AirCloudBinarySensor(coordinator, dev, IDU_THERMO))
    async_add_entities(entities)


class AirCloudBinarySensor(AirCloudEntity, BinarySensorEntity):
    def __init__(self, coordinator, device, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.gateway.host}-{device.uid}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        st = data.idu.get(self._device.index) if self._device.kind == "idu" else data.odu.get(self._device.index)
        if st is None:
            return None
        if self.entity_description.key == "alarm":
            return st.alarm != 0
        return bool(getattr(st, "thermo_on", False))
