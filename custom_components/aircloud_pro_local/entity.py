"""Shared entity base classes."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Device
from .const import DOMAIN, MANUFACTURER
from .coordinator import AirCloudCoordinator


class AirCloudEntity(CoordinatorEntity[AirCloudCoordinator]):
    """Base for all entities; one HA device per indoor/outdoor unit."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AirCloudCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._device = device
        host = coordinator.gateway.host
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{host}-{device.uid}")},
            name=device.display_name if device.kind == "idu" else f"Outdoor unit {device.name}",
            manufacturer=MANUFACTURER,
            model=device.model or ("Indoor unit" if device.kind == "idu" else "Outdoor unit"),
            via_device=(DOMAIN, host),
            configuration_url=f"https://{host}/",
        )

    @property
    def device(self) -> Device:
        # Pick up renames from the periodically refreshed device list.
        return self.coordinator.data.devices.get(self._device.uid, self._device)

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if self._device.kind == "idu":
            return self._device.index in self.coordinator.data.idu
        return self._device.index in self.coordinator.data.odu
