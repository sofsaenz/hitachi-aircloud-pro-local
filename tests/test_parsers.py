"""Parser tests against responses captured from a real airCloud Gateway (W-0159.0008)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "aircloud_pro_local"))

import api  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_device_list():
    devs = api.parse_device_list((FIX / "device_list.html").read_text())
    assert len(devs) == 9
    idus = [d for d in devs if d.kind == "idu"]
    odus = [d for d in devs if d.kind == "odu"]
    assert [d.index for d in idus] == list(range(8))
    assert idus[1].display_name == "Oficina"
    assert idus[2].display_name == "Cuarto niñas"
    assert idus[1].address == 2
    assert odus[0].index == 0
    assert odus[0].model.startswith("RAS-100HNCERW")
    assert odus[0].description == ""  # "Undefined" is blanked
    assert all(d.online for d in devs)


def test_idu_off():
    st = api.parse_idu_status((FIX / "idu_status_off.json").read_text())
    assert st.power is False
    assert st.mode == "cool"
    assert st.fan == "sharp"
    assert st.target_temp == 20.0  # first "Ts", not the correction
    assert st.room_temp == 23.0
    assert st.thermo_on is False
    assert st.compressor_freq == 0
    assert st.alarm == 0
    assert st.capacity == 45


def test_idu_on():
    st = api.parse_idu_status((FIX / "idu_status_on.json").read_text())
    assert st.power is True
    assert st.compressor_freq == 80


def test_odu():
    st = api.parse_odu_status((FIX / "odu_status.json").read_text())
    assert st.ambient_temp == 17
    assert st.discharge_temp == 46
    assert st.discharge_pressure == 1.28
    assert st.suction_pressure == 1.22
    assert st.compressor_freq == 11.1
    assert st.fan_power == 57
    assert st.cycle == "Cooling"
    assert st.state == "Running"
    assert st.alarm == 0


def test_login_detection():
    assert api.is_login_page((FIX / "login.html").read_text())
    assert not api.is_login_page((FIX / "device_list.html").read_text())


def test_mode_codes():
    assert api.MODE_TO_CODE == {"heat": 2, "fan": 1, "dry": 64, "cool": 4, "auto": 8}
    assert api.FAN_TO_CODE == {"weak": 0, "strong": 1, "sharp": 2}
