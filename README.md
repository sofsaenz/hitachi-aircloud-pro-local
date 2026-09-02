# Hitachi airCloud Pro — Local (LAN) integration for Home Assistant

Control Hitachi VRF / multi-split indoor units through the **airCloud Pro gateway's own web
server on your LAN** — no Hitachi cloud account, no internet dependency. Every indoor unit
becomes a `climate` entity; the outdoor unit gets diagnostic sensors.

Tested on: **airCloud Gateway, firmware W-0159.0008** (Johnson Controls-Hitachi), 8 indoor
units on H-Link + one RAS-100HNCERW outdoor unit.

> Existing Hitachi integrations ([aircloud-hass](https://github.com/ylemoigne/aircloud-hass),
> [aircloud_ha](https://github.com/svmironov/aircloud_ha)) talk to the airCloud *Home* cloud API.
> This one talks to the airCloud *Pro* gateway directly at `https://<gateway-ip>/`.

## What you get

| Entity | Per | Notes |
|---|---|---|
| `climate.<room>` | indoor unit | on/off, cool / heat / dry / fan-only, target temperature (16–30 °C, 1 °C steps), fan low / medium / high, current room temperature, hvac_action (cooling / heating / idle / off) |
| `sensor.<room>_room_temperature` | indoor unit | inlet air temperature (`Ti`) |
| `sensor.<room>_compressor_frequency`, `..._outlet_air_temperature`, `..._alarm_code`, coil temps | indoor unit | diagnostic |
| `binary_sensor.<room>_thermo_on`, `..._alarm` | indoor unit | thermostat demand / fault |
| `sensor.outdoor_unit_odu_000_outdoor_temperature` | outdoor unit | ambient temperature (`Ta`) |
| `..._compressor_frequency`, `..._discharge_temperature`, `..._discharge_pressure`, `..._suction_pressure`, `..._fan_power`, `..._cycle`, `..._alarm` | outdoor unit | diagnostic |

Unit names come from the **Description** column of the gateway's *Device List* page, so
whatever you named the rooms there is what shows up in Home Assistant.

The gateway only exposes the modes the units support. On the tested system there is no
*Auto* mode and no *Auto* fan speed, so they are not offered.

## Installation

### HACS (recommended)
1. HACS → Integrations → ⋮ → **Custom repositories** → add this repo URL, category *Integration*.
2. Install **Hitachi airCloud Pro (Local)** and restart Home Assistant.

### Manual
Copy `custom_components/aircloud_pro_local` into `<config>/custom_components/` and restart.

### Configure
Settings → Devices & services → **Add integration** → *Hitachi airCloud Pro (Local)*.
Enter the gateway IP (e.g. `10.24.10.70`) and the same username/password you use on its web page.

Options (⚙ on the integration): polling interval, default 15 s (min 5 s). The gateway's own
GUI polls every 1–5 s so 10–15 s is safe.

Tip: give the gateway a fixed IP / DHCP reservation on your router.

## Dashboard

`examples/dashboard.yaml` has a ready-made view with a thermostat card per room, a room
temperature glance and the outdoor unit. Entity ids are derived from the room names
(`Cuarto niñas` → `climate.cuarto_ninas`); check them under Settings → Entities if yours differ.

## How it works (protocol)

Reverse-engineered from the gateway's embedded web GUI. All requests go to
`https://<ip>/index.cgi` (self-signed certificate; HTTP redirects to HTTPS).

| Purpose | Request |
|---|---|
| Login | `POST mod=0&act=1&username=…&password=…` → session cookie |
| Device list | `GET ?mod=1&act=11` → HTML rows `IDU-000…`, `ODU-000…` with description, address, model |
| Indoor unit status | `GET ?mod=3&act=35&dev=<n>` → JSON: `Operation` ON/OFF, `Mode`, `Rair` (fan), `Ts` setpoint, `Ti` room temp, `To` outlet, `Therm`, `ALM`, `fd` (compressor Hz) … |
| Outdoor unit status | `GET ?mod=3&act=36&dev=<n>` → JSON: `Ta` ambient, `Td` discharge, `Pd`/`Ps` pressures (MPa), `H1` compressor Hz, `FANPower`, `Cycle`, `state`, `Alarm` |
| Control | `POST mod=3&act=33&dev=<n>&OnOf=0|1&OpeM=<mode>&FanS=<fan>&Ts=<°C>` |

Codes: `OpeM` — Heat `2`, Fan `1`, Dry `64`, Cool `4` (Auto `8`, if the unit offers it).
`FanS` — Weak `0`, Strong `1`, Sharp `2` (mapped to HA low / medium / high).

Quirks handled by the client: the JSON is prefixed with `\r` and contains the key `Ts` twice
(setpoint first, then the "Ts correction"); the session cookie comes from an IP host so an
`unsafe` cookie jar is required; the gateway answers a login page instead of a 401 when the
session expires — the client re-logs in transparently.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install homeassistant pytest pytest-asyncio pytest-homeassistant-custom-component
pytest -q
```

`tests/fixtures/` holds real responses captured from the gateway; `tests/test_integration.py`
spins up a fake gateway HTTP server and drives the integration end-to-end (config flow,
entity creation, every climate service call, session-expiry re-login).

## Disclaimer

Not affiliated with Hitachi or Johnson Controls. Use at your own risk; the control endpoint
sends real commands to your HVAC equipment.
