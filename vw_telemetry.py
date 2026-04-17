"""VW ID.7 Telemetrie — direkt per WeConnect API."""

import logging
from weconnect import weconnect

_log = logging.getLogger(__name__)

_api: weconnect.WeConnect | None = None
_vin: str = ""


def init(username: str, password: str, vin: str):
    global _api, _vin
    _vin = vin
    try:
        _api = weconnect.WeConnect(username=username, password=password, updateAfterLogin=False)
        _api.login()
        _log.info("[vw] Login OK — VIN %s", vin)
    except Exception as e:
        _log.error("[vw] Login fehlgeschlagen: %s", e)
        _api = None


def get_telemetry() -> list[str]:
    """Aktuelle Fahrzeugdaten als HUD-Zeilen."""
    if not _api or not _vin:
        return []
    lines = []
    try:
        _api.update()
        v = _api.vehicles[_vin]

        # Battery
        try:
            bs = v.domains["charging"]["batteryStatus"]
            soc = bs.currentSOC_pct.value
            rng = bs.cruisingRangeElectric_km.value
            lines.append(f"VW ID.7 SOC: {soc}%")
            lines.append(f"VW ID.7 RANGE: {rng} KM")
        except Exception:
            pass

        # Charging
        try:
            cs = v.domains["charging"]["chargingStatus"]
            state = cs.chargingState.value
            state_str = str(state).split(".")[-1].replace("_", " ")
            power = cs.chargePower_kW.value
            if power and float(power) > 0:
                lines.append(f"VW ID.7 CHARGING: {power} KW")
            else:
                lines.append(f"VW ID.7 STATUS: {state_str}")
        except Exception:
            pass

        # Odometer
        try:
            ms = v.domains["measurements"]["odometerStatus"]
            lines.append(f"VW ID.7 ODOMETER: {ms.odometer.value} KM")
        except Exception:
            pass

    except Exception as e:
        _log.warning("[vw] Update error: %s", e)
        # Try re-login on next cycle
        try:
            _api.login()
        except Exception:
            pass
    return lines
