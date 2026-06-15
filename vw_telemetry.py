"""VW ID.7 Telemetrie.

Drei Modi (config.json -> vw_mode):
  "off"       — komplett inaktiv (Default seit VW-Auth-Aenderung 06/2026)
  "ha"        — liest VW-Daten aus Home Assistant (carconnectivity-volkswagen-eu)
  "weconnect" — direkte WeConnect-API (aktuell defekt: KeyError 'location',
                siehe https://github.com/tillsteinbach/WeConnect-python/issues/236)
"""

import json
import logging
import urllib.request
import urllib.error

import paho.mqtt.client as mqtt

_log = logging.getLogger(__name__)

_mode: str = "off"
_vin: str = ""

# --- WeConnect Mode ---
_api = None  # weconnect.WeConnect instance, lazy import
_mqtt: mqtt.Client | None = None
_mqtt_discovery_sent: bool = False

# --- HA Mode ---
_ha_url: str = ""
_ha_token: str = ""

# Mapping interne Key -> HA entity_id (carconnectivity-volkswagen-eu Naming)
_HA_ENTITIES = {
    "soc":                  "sensor.vw_id_7_vw_id_7_ladestand",
    "range":                "sensor.vw_id_7_vw_id_7_reichweite",
    "charging_state":       "sensor.vw_id_7_vw_id_7_ladestatus",
    "charge_power":         "sensor.vw_id_7_vw_id_7_ladeleistung",
    "charge_rate":          "sensor.vw_id_7_vw_id_7_laderate",
    "charge_type":          "sensor.vw_id_7_vw_id_7_ladetyp",
    "charge_mode":          "sensor.vw_id_7_vw_id_7_lademodus",
    "remaining_charge_time":"sensor.vw_id_7_vw_id_7_restladezeit",
    "target_soc":           "sensor.vw_id_7_vw_id_7_ziel_ladestand",
    "max_charge_current":   "sensor.vw_id_7_vw_id_7_max_ladestrom_ac",
    "plug_connection":      "sensor.vw_id_7_vw_id_7_stecker_verbindung",
    "plug_lock":            "sensor.vw_id_7_vw_id_7_stecker_verriegelung",
    "external_power":       "sensor.vw_id_7_vw_id_7_externe_stromversorgung",
    "battery_care":         "sensor.vw_id_7_vw_id_7_batteriepflege",
    "odometer":             "sensor.vw_id_7_vw_id_7_kilometerstand",
    "door_lock":            "sensor.vw_id_7_vw_id_7_turschloss",
    "overall_status":       "sensor.vw_id_7_vw_id_7_gesamtstatus_sicherheit",
    "climatisation_state":  "sensor.vw_id_7_vw_id_7_klimatisierung_status",
    "target_temp":          "sensor.vw_id_7_vw_id_7_zieltemperatur",
    "temp_outside":         "sensor.vw_id_7_vw_id_7_aussentemperatur",
    "temp_battery_min":     "sensor.vw_id_7_vw_id_7_hv_batterie_temp_min",
    "temp_battery_max":     "sensor.vw_id_7_vw_id_7_hv_batterie_temp_max",
    "inspection_days":      "sensor.vw_id_7_vw_id_7_inspektion_fallig_in",
    "park_latitude":        "sensor.vw_id_7_vw_id_7_parkposition_breitengrad",
    "park_longitude":       "sensor.vw_id_7_vw_id_7_parkposition_langengrad",
}

# Connector-Health-Sensor zum Pruefen ob HA-Integration laeuft
_HA_CONNECTOR_STATE = "sensor.carconnectivity_volkswagen_eu_data_act_connector_connection_state"


def init(mode: str = "off",
         vin: str = "",
         ha_url: str = "",
         ha_token: str = "",
         # WeConnect-spezifisch (nur fuer mode="weconnect"):
         vw_username: str = "",
         vw_password: str = "",
         mqtt_host: str = "192.167.178.110",
         mqtt_user: str = "jarvis",
         mqtt_pass: str = "jarvis-mqtt-2026"):
    """Initialisiert das VW-Telemetrie-Modul im gewaehlten Modus."""
    global _mode, _vin, _ha_url, _ha_token, _api, _mqtt
    _mode = mode
    _vin = vin

    if mode == "off":
        print("[vw] Modus: off (deaktiviert)", flush=True)
        return

    if mode == "ha":
        _ha_url = ha_url.rstrip("/")
        _ha_token = ha_token
        if not _ha_url or not _ha_token:
            print("[vw] HA-Modus FEHLER: ha_url oder ha_token fehlt", flush=True)
            _mode = "off"
            return
        print(f"[vw] Modus: ha (liest aus {_ha_url})", flush=True)
        return

    if mode == "weconnect":
        # Lazy import — Library nur laden wenn aktiv genutzt
        try:
            from weconnect import weconnect
            _api = weconnect.WeConnect(username=vw_username, password=vw_password,
                                       updateAfterLogin=False)
            _api.login()
            _log.info("[vw] WeConnect Login OK — VIN %s", vin)
        except Exception as e:
            _log.error("[vw] WeConnect Login fehlgeschlagen: %s", e)
            _api = None

        try:
            _mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jarvis-vw")
            _mqtt.username_pw_set(mqtt_user, mqtt_pass)
            _mqtt.connect(mqtt_host, 1883, 60)
            _mqtt.loop_start()
            print(f"[vw] MQTT verbunden: {mqtt_host}", flush=True)
        except Exception as e:
            print(f"[vw] MQTT Fehler: {e}", flush=True)
            _mqtt = None
        return

    print(f"[vw] Unbekannter Modus '{mode}' — deaktiviere", flush=True)
    _mode = "off"


# ---------------------------------------------------------------------------
# HA-Mode Implementierung
# ---------------------------------------------------------------------------

def _ha_get_state(entity_id: str) -> str | None:
    """Holt den State eines HA-Entities. Gibt None bei Fehler/unavailable."""
    url = f"{_ha_url}/api/states/{entity_id}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_ha_token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
        return None
    state = data.get("state")
    if state in (None, "", "unknown", "unavailable"):
        return None
    return state


def _ha_collect() -> dict:
    """Liest alle VW-Werte aus HA."""
    out = {}
    for key, entity_id in _HA_ENTITIES.items():
        val = _ha_get_state(entity_id)
        if val is not None:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# WeConnect-Mode Hilfsfunktionen (unveraendert aus alter Version)
# ---------------------------------------------------------------------------

def _enum_str(val):
    s = str(val)
    return s.split(".")[-1].replace("_", " ") if "." in s else s


def _kelvin_to_celsius(k):
    try:
        return round(float(k) - 273.15, 1)
    except (TypeError, ValueError):
        return None


def _safe_val(obj, *attrs):
    try:
        current = obj
        for a in attrs:
            current = getattr(current, a)
        return current.value if hasattr(current, "value") else current
    except Exception:
        return None


def _wc_collect_all(v) -> dict:
    """Alle Werte aus dem WeConnect-Fahrzeug-Objekt extrahieren."""
    d = {}
    try:
        bat = v.domains["charging"]["batteryStatus"]
        d["soc"] = _safe_val(bat, "currentSOC_pct")
        d["range"] = _safe_val(bat, "cruisingRangeElectric_km")
    except Exception:
        pass
    try:
        cs = v.domains["charging"]["chargingStatus"]
        d["charging_state"] = _enum_str(_safe_val(cs, "chargingState"))
        d["charge_power"] = _safe_val(cs, "chargePower_kW") or 0
        d["charge_rate"] = _safe_val(cs, "chargeRate_kmph") or 0
        d["remaining_charge_time"] = _safe_val(cs, "remainingChargingTimeToComplete_min") or 0
    except Exception:
        pass
    try:
        odo = v.domains["measurements"]["odometerStatus"]
        d["odometer"] = _safe_val(odo, "odometer")
    except Exception:
        pass
    try:
        to = v.domains["measurements"]["temperatureOutsideStatus"]
        d["temp_outside"] = _kelvin_to_celsius(_safe_val(to, "temperatureOutside_K"))
    except Exception:
        pass
    return d


# ---------------------------------------------------------------------------
# Public API: get_telemetry()
# ---------------------------------------------------------------------------

def _hud_lines(data: dict) -> list[str]:
    """Aus dem Daten-Dict die HUD-Terminal-Zeilen bauen."""
    lines = []
    if data.get("soc") is not None:
        lines.append(f"VW ID.7 SOC: {data['soc']}%")
    if data.get("range") is not None:
        lines.append(f"VW ID.7 RANGE: {data['range']} KM")
    cp = data.get("charge_power")
    try:
        if cp is not None and float(cp) > 0:
            lines.append(f"VW ID.7 CHARGING: {cp} KW")
        else:
            cs = data.get("charging_state", "")
            if cs:
                lines.append(f"VW ID.7 STATUS: {cs}")
    except (TypeError, ValueError):
        pass
    if data.get("odometer") is not None:
        lines.append(f"VW ID.7 ODOMETER: {data['odometer']} KM")
    return lines


def get_telemetry() -> list[str]:
    """Aktuelle Fahrzeugdaten als HUD-Zeilen."""
    if _mode == "off":
        return []

    if _mode == "ha":
        # Erst Connector-State pruefen — wenn HA-Integration tot, gar nicht erst sammeln
        conn = _ha_get_state(_HA_CONNECTOR_STATE)
        if conn != "connected":
            return []
        try:
            data = _ha_collect()
            return _hud_lines(data)
        except Exception as e:
            _log.warning("[vw] HA-Read error: %s", e)
            return []

    if _mode == "weconnect":
        if not _api or not _vin:
            return []
        try:
            _api.update()
            v = _api.vehicles[_vin]
            data = _wc_collect_all(v)
            return _hud_lines(data)
        except Exception as e:
            _log.warning("[vw] Update error: %s", e)
            try:
                _api.login()
            except Exception:
                pass
            return []

    return []
