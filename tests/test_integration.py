"""End-to-end tests with a fake gateway HTTP server (requires pytest-homeassistant-custom-component)."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.aircloud_pro_local.const import DOMAIN

FIX = Path(__file__).parent / "fixtures"

pytestmark = [pytest.mark.asyncio, pytest.mark.enable_socket]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeGateway:
    """Mimics index.cgi closely enough: cookie login, HTML list, JSON status, control POST."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.operation = {i: "OFF" for i in range(8)}
        self.logged_in_cookie = "abc"

    def _authed(self, request) -> bool:
        return request.cookies.get("sid") == self.logged_in_cookie

    async def handle(self, request: web.Request) -> web.Response:
        if request.method == "POST":
            form = dict(await request.post())
            if form.get("mod") == "0" and form.get("act") == "1":
                if form.get("username") == "admin" and form.get("password") == "pw":
                    resp = web.Response(text=(FIX / "device_list.html").read_text(), content_type="text/html")
                    resp.set_cookie("sid", self.logged_in_cookie)
                    return resp
                return web.Response(text=(FIX / "login.html").read_text(), content_type="text/html")
            if not self._authed(request):
                return web.Response(text=(FIX / "login.html").read_text(), content_type="text/html")
            if form.get("mod") == "3" and form.get("act") == "33":
                self.posts.append(form)
                self.operation[int(form["dev"])] = "ON" if form["OnOf"] == "1" else "OFF"
                return web.Response(text="<html><title>Device List</title></html>", content_type="text/html")
            return web.Response(status=400)

        if not self._authed(request):
            return web.Response(text=(FIX / "login.html").read_text(), content_type="text/html")
        q = request.query
        if q.get("mod") == "1" and q.get("act") == "11":
            return web.Response(text=(FIX / "device_list.html").read_text(), content_type="text/html")
        if q.get("mod") == "3" and q.get("act") == "35":
            dev = int(q["dev"])
            body = (FIX / "idu_status_off.json").read_text().replace('"Operation":"OFF"', f'"Operation":"{self.operation[dev]}"')
            return web.Response(text=body)
        if q.get("mod") == "3" and q.get("act") == "36":
            return web.Response(text=(FIX / "odu_status.json").read_text())
        return web.Response(status=404)


@pytest.fixture
async def fake_gateway(socket_enabled, aiohttp_server, monkeypatch):
    gw = FakeGateway()
    app = web.Application()
    app.router.add_route("*", "/index.cgi", gw.handle)
    server = await aiohttp_server(app)
    # The real gateway is HTTPS; point the client at our plain-HTTP test server.
    from custom_components.aircloud_pro_local import api

    orig_init = api.AirCloudGateway.__init__

    def patched_init(self, host, username, password, session, **kw):
        orig_init(self, host, username, password, session, **kw)
        self._base = f"http://{server.host}:{server.port}"

    monkeypatch.setattr(api.AirCloudGateway, "__init__", patched_init)
    return gw


async def _setup(hass: HomeAssistant, password="pw") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "10.24.10.70", CONF_USERNAME: "admin", CONF_PASSWORD: password},
        unique_id="10.24.10.70",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_created(hass: HomeAssistant, fake_gateway):
    entry = await _setup(hass)
    assert entry.state.name == "LOADED"

    climates = hass.states.async_entity_ids(CLIMATE_DOMAIN)
    assert len(climates) == 8
    oficina = hass.states.get("climate.oficina")
    assert oficina is not None
    assert oficina.state == HVACMode.OFF
    assert oficina.attributes["current_temperature"] == 23.0
    assert oficina.attributes["temperature"] == 20.0
    assert oficina.attributes["fan_mode"] == "high"
    assert "cuarto_ninas" in " ".join(climates)

    outdoor = hass.states.get("sensor.outdoor_unit_odu_000_outdoor_temperature")
    assert outdoor is not None and float(outdoor.state) == 17.0


async def test_set_mode_temperature_fan(hass: HomeAssistant, fake_gateway):
    await _setup(hass)

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: "climate.oficina", ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )
    await hass.async_block_till_done()
    post = fake_gateway.posts[-1]
    assert post == {"mod": "3", "act": "33", "dev": "1", "OnOf": "1", "OpeM": "4", "FanS": "2", "Ts": "20.0"}
    assert hass.states.get("climate.oficina").state == HVACMode.COOL

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: "climate.oficina", ATTR_TEMPERATURE: 22},
        blocking=True,
    )
    assert fake_gateway.posts[-1]["Ts"] == "22.0"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: "climate.sala", ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )
    assert fake_gateway.posts[-1]["OpeM"] == "2" and fake_gateway.posts[-1]["dev"] == "3"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: "climate.sala", ATTR_FAN_MODE: "low"},
        blocking=True,
    )
    assert fake_gateway.posts[-1]["FanS"] == "0"

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: "climate.sala", ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    assert fake_gateway.posts[-1]["OnOf"] == "0"


async def test_bad_password(hass: HomeAssistant, fake_gateway):
    entry = await _setup(hass, password="wrong")
    assert entry.state.name == "SETUP_ERROR"


async def test_session_expiry_relogin(hass: HomeAssistant, fake_gateway):
    entry = await _setup(hass)
    coordinator = entry.runtime_data
    fake_gateway.logged_in_cookie = "rotated"  # invalidates the current cookie
    await coordinator.async_refresh()
    assert coordinator.last_update_success


async def test_config_flow(hass: HomeAssistant, fake_gateway):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "https://10.24.10.70/", CONF_USERNAME: "admin", CONF_PASSWORD: "pw"}
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"][CONF_HOST] == "10.24.10.70"
