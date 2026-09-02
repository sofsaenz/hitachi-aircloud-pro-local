"""aiohttp session factory for the gateway.

The gateway is addressed by IP and issues a session cookie; aiohttp's default CookieJar
discards cookies from IP hosts, so we need `unsafe=True`. It also uses a self-signed
TLS certificate, so verification is disabled for this session only.
"""
from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession


def create_gateway_session(hass: HomeAssistant, *, auto_cleanup: bool = True) -> aiohttp.ClientSession:
    return async_create_clientsession(
        hass,
        verify_ssl=False,
        auto_cleanup=auto_cleanup,
        cookie_jar=aiohttp.CookieJar(unsafe=True),
    )
