"""Hitachi airCloud Pro (local LAN) integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .api import AirCloudGateway
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DEFAULT_TIMEOUT, PLATFORMS
from .coordinator import AirCloudCoordinator
from .session import create_gateway_session

AirCloudConfigEntry = ConfigEntry[AirCloudCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AirCloudConfigEntry) -> bool:
    """Set up from a config entry."""
    # Own session per gateway: self-signed cert + cookie jar that accepts IP hosts.
    session = create_gateway_session(hass)
    gateway = AirCloudGateway(
        entry.data[CONF_HOST],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        session,
        timeout=DEFAULT_TIMEOUT,
    )
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = AirCloudCoordinator(hass, entry, gateway, scan_interval)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: AirCloudConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AirCloudConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
