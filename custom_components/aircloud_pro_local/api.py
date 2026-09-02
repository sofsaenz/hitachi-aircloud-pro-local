"""Local HTTP client for the Hitachi / Johnson Controls airCloud Gateway (airCloud Pro).

Protocol (reverse-engineered from the gateway's embedded web GUI, firmware W-0159.0008):

    POST /index.cgi            mod=0&act=1&username=..&password=..       -> cookie session
    GET  /index.cgi?mod=1&act=11                                          -> device list (HTML)
    GET  /index.cgi?mod=3&act=35&dev=<n>                                  -> indoor unit status (JSON)
    GET  /index.cgi?mod=3&act=36&dev=<n>                                  -> outdoor unit status (JSON)
    POST /index.cgi            mod=3&act=33&dev=<n>&OnOf=&OpeM=&FanS=&Ts= -> control indoor unit

The gateway serves HTTPS with a self-signed certificate and redirects HTTP to HTTPS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# ---- Protocol constants ----------------------------------------------------

# Values accepted by the control form (select "OpeM")
MODE_TO_CODE: dict[str, int] = {"heat": 2, "fan": 1, "dry": 64, "cool": 4, "auto": 8}
CODE_TO_MODE: dict[int, str] = {v: k for k, v in MODE_TO_CODE.items()}
# Strings reported by the status JSON ("Mode")
MODE_TEXT_TO_MODE: dict[str, str] = {
    "cool": "cool",
    "heat": "heat",
    "fan": "fan",
    "dry": "dry",
    "auto": "auto",
}

# Values accepted by the control form (select "FanS") and reported in "Rair"
FAN_TO_CODE: dict[str, int] = {"weak": 0, "strong": 1, "sharp": 2}
FAN_TEXT_TO_FAN: dict[str, str] = {"weak": "weak", "strong": "strong", "sharp": "sharp", "auto": "auto"}

MIN_TEMP = 16.0
MAX_TEMP = 30.0


class AirCloudError(Exception):
    """Base error."""


class AirCloudAuthError(AirCloudError):
    """Login rejected."""


class AirCloudConnectionError(AirCloudError):
    """Gateway unreachable."""


# ---- Data models -----------------------------------------------------------


@dataclass
class Device:
    """A row from the gateway device list."""

    kind: str  # "idu" or "odu"
    index: int  # `dev` parameter
    name: str  # e.g. IDU-001
    description: str  # user label, e.g. "Oficina"
    address: int | None
    model: str
    system: str
    online: bool = True

    @property
    def uid(self) -> str:
        return f"{self.kind}{self.index}"

    @property
    def display_name(self) -> str:
        return self.description or self.name


@dataclass
class IduState:
    """Parsed indoor-unit status."""

    power: bool
    mode: str | None  # cool/heat/fan/dry/auto
    fan: str | None  # weak/strong/sharp/auto
    target_temp: float | None  # Ts
    room_temp: float | None  # Ti (inlet air)
    outlet_temp: float | None  # To
    coil_liquid_temp: float | None  # Tl
    coil_gas_temp: float | None  # Tg
    thermo_on: bool
    compressor_freq: float | None  # fd
    alarm: int
    capacity: int | None
    remote_controller: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OduState:
    """Parsed outdoor-unit status."""

    ambient_temp: float | None  # Ta
    discharge_temp: float | None  # Td
    discharge_pressure: float | None  # Pd (MPa)
    suction_pressure: float | None  # Ps (MPa)
    compressor_freq: float | None  # H1 (Hz)
    fan_power: float | None  # FANPower (%)
    cycle: str  # Cooling/Heating
    state: str  # Running/Stopped
    alarm: int
    raw: dict[str, Any] = field(default_factory=dict)


# ---- Parsers (pure functions, unit-tested) ---------------------------------


def _first_wins(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """json object_pairs_hook keeping the FIRST duplicate key.

    The gateway emits "Ts" twice (setpoint, then Ts-correction); the setpoint comes first.
    """
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k not in out:
            out[k] = v
        else:
            out.setdefault(f"{k}__{sum(1 for x in out if x.startswith(k + '__')) + 2}", v)
    return out


def parse_gateway_json(text: str) -> dict[str, Any]:
    """Parse the gateway's slightly malformed JSON (leading CR, duplicate keys)."""
    text = text.strip()
    if not text.startswith("{"):
        raise AirCloudError(f"Unexpected non-JSON response: {text[:80]!r}")
    return json.loads(text, object_pairs_hook=_first_wins)


def _to_float(v: Any) -> float | None:
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return default


def parse_idu_status(text: str) -> IduState:
    d = parse_gateway_json(text)
    mode_txt = str(d.get("Mode", "")).strip().lower()
    fan_txt = str(d.get("Rair", "")).strip().lower()
    return IduState(
        power=str(d.get("Operation", "")).strip().upper() == "ON",
        mode=MODE_TEXT_TO_MODE.get(mode_txt),
        fan=FAN_TEXT_TO_FAN.get(fan_txt),
        target_temp=_to_float(d.get("Ts")),
        room_temp=_to_float(d.get("Ti")),
        outlet_temp=_to_float(d.get("To")),
        coil_liquid_temp=_to_float(d.get("Tl")),
        coil_gas_temp=_to_float(d.get("Tg")),
        thermo_on=str(d.get("Therm", "")).strip().upper() == "ON",
        compressor_freq=_to_float(d.get("fd")),
        alarm=_to_int(d.get("ALM")),
        capacity=_to_int(d.get("Capacity")) or None,
        remote_controller=str(d.get("Remote", "")).strip(),
        raw=d,
    )


def parse_odu_status(text: str) -> OduState:
    d = parse_gateway_json(text)
    return OduState(
        ambient_temp=_to_float(d.get("Ta")),
        discharge_temp=_to_float(d.get("Td")),
        discharge_pressure=_to_float(d.get("Pd")),
        suction_pressure=_to_float(d.get("Ps")),
        compressor_freq=_to_float(d.get("H1")),
        fan_power=_to_float(d.get("FANPower")),
        cycle=str(d.get("Cycle", "")).strip(),
        state=str(d.get("state", "")).strip(),
        alarm=_to_int(d.get("Alarm")),
        raw=d,
    )


_ROW_RE = re.compile(r"<tr\s+class=[\"']device([^\"']*)[\"'][^>]*>(.*?)</tr>", re.S | re.I)
_NAME_RE = re.compile(r"class=[\"']name[^\"']*[\"'][^>]*>\s*<div[^>]*>\s*([^<]+?)\s*</div>", re.S | re.I)
_DESC_RE = re.compile(r"class=[\"']myshow[\"'][^>]*>\s*([^<]*?)\s*</div>", re.S | re.I)
_DEV_RE = re.compile(r"act=(\d+)(?:&amp;|&)dev=(\d+)", re.I)
_ADDR_RE = re.compile(r"class=[\"']address[\"'][^>]*>\s*<span[^>]*>\s*([^<]*?)\s*</span>", re.S | re.I)
_MODEL_RE = re.compile(r"class=[\"']model[^\"']*[\"'][^>]*>\s*<span[^>]*>\s*([^<]*?)\s*</span>", re.S | re.I)
_SYSTEM_RE = re.compile(r"system-(\d+)", re.I)


def parse_device_list(html: str) -> list[Device]:
    """Extract IDU/ODU rows from the device list page (mod=1&act=11)."""
    devices: list[Device] = []
    for m in _ROW_RE.finditer(html):
        cls, body = m.group(1), m.group(2)
        name_m = _NAME_RE.search(body)
        if not name_m:
            continue
        name = name_m.group(1).strip()
        kind = "idu" if name.upper().startswith("IDU") else "odu" if name.upper().startswith("ODU") else None
        if kind is None:
            continue
        dev_m = _DEV_RE.search(body)
        if dev_m:
            index = int(dev_m.group(2))
        else:
            # Fall back to the number in the name (IDU-003 -> 3)
            num = re.search(r"(\d+)$", name)
            index = int(num.group(1)) if num else len(devices)
        desc_m = _DESC_RE.search(body)
        desc = desc_m.group(1).strip() if desc_m else ""
        if desc.lower() == "undefined":
            desc = ""
        addr_m = _ADDR_RE.search(body)
        model_m = _MODEL_RE.search(body)
        sys_m = _SYSTEM_RE.search(cls)
        devices.append(
            Device(
                kind=kind,
                index=index,
                name=name,
                description=desc,
                address=_to_int(addr_m.group(1)) if addr_m and addr_m.group(1).strip() else None,
                model=(model_m.group(1).strip() if model_m else ""),
                system=sys_m.group(1) if sys_m else "0",
                online="status-offline" not in cls,
            )
        )
    return devices


def is_login_page(html: str) -> bool:
    return bool(re.search(r"<title>\s*Login\s*</title>", html, re.I)) or 'name="password"' in html


# ---- Client ----------------------------------------------------------------


class AirCloudGateway:
    """Async client. One instance per gateway; serialises requests with a lock."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession,
        *,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._base = f"https://{host}"
        self._username = username
        self._password = password
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._lock = asyncio.Lock()
        self._logged_in = False

    @property
    def host(self) -> str:
        return self._host

    # -- low level ----------------------------------------------------------

    async def _request(self, method: str, params: dict | None = None, data: dict | None = None) -> str:
        url = f"{self._base}/index.cgi"
        try:
            async with self._session.request(
                method,
                url,
                params=params,
                data=data,
                timeout=self._timeout,
                ssl=False,
                allow_redirects=True,
            ) as resp:
                resp.raise_for_status()
                return await resp.text(errors="replace")
        except asyncio.TimeoutError as err:
            raise AirCloudConnectionError(f"Timeout talking to {self._host}") from err
        except aiohttp.ClientError as err:
            raise AirCloudConnectionError(f"Cannot reach {self._host}: {err}") from err

    async def login(self) -> None:
        html = await self._request(
            "POST",
            data={"mod": "0", "act": "1", "username": self._username, "password": self._password},
        )
        if is_login_page(html):
            self._logged_in = False
            raise AirCloudAuthError("Gateway rejected username/password")
        self._logged_in = True

    async def _authed(self, method: str, params: dict | None = None, data: dict | None = None) -> str:
        """Run a request, (re)logging in when the session cookie has expired."""
        async with self._lock:
            if not self._logged_in:
                await self.login()
            text = await self._request(method, params, data)
            if is_login_page(text):
                _LOGGER.debug("Session expired on %s, re-authenticating", self._host)
                await self.login()
                text = await self._request(method, params, data)
                if is_login_page(text):
                    raise AirCloudAuthError("Still on login page after re-authentication")
            return text

    # -- high level ---------------------------------------------------------

    async def async_get_devices(self) -> list[Device]:
        html = await self._authed("GET", params={"mod": "1", "act": "11"})
        devices = parse_device_list(html)
        if not devices:
            raise AirCloudError("Device list page contained no units")
        return devices

    async def async_get_idu_status(self, index: int) -> IduState:
        text = await self._authed("GET", params={"mod": "3", "act": "35", "dev": str(index)})
        return parse_idu_status(text)

    async def async_get_odu_status(self, index: int) -> OduState:
        text = await self._authed("GET", params={"mod": "3", "act": "36", "dev": str(index)})
        return parse_odu_status(text)

    async def async_set_idu(
        self,
        index: int,
        *,
        power: bool,
        mode: str,
        fan: str,
        target_temp: float,
    ) -> None:
        """Send the full control form (the GUI always posts every field)."""
        if mode not in MODE_TO_CODE:
            raise ValueError(f"Unsupported mode {mode!r}")
        if fan not in FAN_TO_CODE:
            fan = "sharp"
        target_temp = max(MIN_TEMP, min(MAX_TEMP, float(target_temp)))
        data = {
            "mod": "3",
            "act": "33",
            "dev": str(index),
            "OnOf": "1" if power else "0",
            "OpeM": str(MODE_TO_CODE[mode]),
            "FanS": str(FAN_TO_CODE[fan]),
            "Ts": f"{target_temp:.1f}",
        }
        _LOGGER.debug("Control dev=%s: %s", index, data)
        await self._authed("POST", data=data)
