"""VW ID.7 Telemetrie — direkt per WeConnect API + MQTT Autodiscovery."""

import json
import logging
import paho.mqtt.client as mqtt
from weconnect import weconnect

_log = logging.getLogger(__name__)

_api: weconnect.WeConnect | None = None
_vin: str = ""
_mqtt: mqtt.Client | None = None
_mqtt_discovery_sent: bool = False

# Alle Sensoren die per MQTT Autodiscovery an HA gesendet werden
ALL_SENSORS = [
    # === Charging / Batterie ===
    {"id": "soc", "name": "Ladestand", "unit": "%", "dc": "battery", "icon": "mdi:car-electric", "sc": "measurement"},
    {"id": "range", "name": "Reichweite", "unit": "km", "dc": None, "icon": "mdi:map-marker-distance", "sc": "measurement"},
    {"id": "charging_state", "name": "Ladestatus", "unit": None, "dc": None, "icon": "mdi:ev-station", "sc": None},
    {"id": "charge_power", "name": "Ladeleistung", "unit": "kW", "dc": "power", "icon": "mdi:flash", "sc": "measurement"},
    {"id": "charge_rate", "name": "Laderate", "unit": "km/h", "dc": None, "icon": "mdi:speedometer", "sc": "measurement"},
    {"id": "charge_type", "name": "Ladetyp", "unit": None, "dc": None, "icon": "mdi:ev-plug-type2", "sc": None},
    {"id": "charge_mode", "name": "Lademodus", "unit": None, "dc": None, "icon": "mdi:battery-charging", "sc": None},
    {"id": "remaining_charge_time", "name": "Restladezeit", "unit": "min", "dc": "duration", "icon": "mdi:timer-sand", "sc": None},
    {"id": "target_soc", "name": "Ziel-Ladestand", "unit": "%", "dc": None, "icon": "mdi:battery-arrow-up", "sc": None},
    {"id": "max_charge_current", "name": "Max Ladestrom AC", "unit": None, "dc": None, "icon": "mdi:current-ac", "sc": None},
    {"id": "plug_connection", "name": "Stecker Verbindung", "unit": None, "dc": None, "icon": "mdi:power-plug", "sc": None},
    {"id": "plug_lock", "name": "Stecker Verriegelung", "unit": None, "dc": None, "icon": "mdi:lock", "sc": None},
    {"id": "external_power", "name": "Externe Stromversorgung", "unit": None, "dc": None, "icon": "mdi:power-plug-outline", "sc": None},
    {"id": "auto_unlock_plug", "name": "Auto-Entriegelung Stecker", "unit": None, "dc": None, "icon": "mdi:lock-open", "sc": None},
    {"id": "battery_care", "name": "Batteriepflege", "unit": None, "dc": None, "icon": "mdi:battery-heart-variant", "sc": None},
    {"id": "led_color", "name": "LED Farbe", "unit": None, "dc": None, "icon": "mdi:led-on", "sc": None},
    # === Kilometerstand ===
    {"id": "odometer", "name": "Kilometerstand", "unit": "km", "dc": "distance", "icon": "mdi:counter", "sc": "total_increasing"},
    # === Zugang / Tueren ===
    {"id": "door_lock", "name": "Türschloss", "unit": None, "dc": None, "icon": "mdi:car-door-lock", "sc": None},
    {"id": "overall_status", "name": "Gesamtstatus Sicherheit", "unit": None, "dc": None, "icon": "mdi:shield-car", "sc": None},
    # === Klimatisierung ===
    {"id": "climatisation_state", "name": "Klimatisierung Status", "unit": None, "dc": None, "icon": "mdi:fan", "sc": None},
    {"id": "climatisation_remaining", "name": "Klimatisierung Restzeit", "unit": "min", "dc": None, "icon": "mdi:timer", "sc": None},
    {"id": "target_temp", "name": "Zieltemperatur", "unit": "°C", "dc": "temperature", "icon": "mdi:thermometer", "sc": "measurement"},
    {"id": "climatise_at_unlock", "name": "Klimatisierung bei Entriegelung", "unit": None, "dc": None, "icon": "mdi:fan-auto", "sc": None},
    {"id": "window_heating", "name": "Scheibenheizung", "unit": None, "dc": None, "icon": "mdi:car-defrost-front", "sc": None},
    {"id": "seat_heating_fl", "name": "Sitzheizung Vorne Links", "unit": None, "dc": None, "icon": "mdi:car-seat-heater", "sc": None},
    {"id": "seat_heating_fr", "name": "Sitzheizung Vorne Rechts", "unit": None, "dc": None, "icon": "mdi:car-seat-heater", "sc": None},
    # === Temperaturen ===
    {"id": "temp_outside", "name": "Außentemperatur", "unit": "°C", "dc": "temperature", "icon": "mdi:thermometer", "sc": "measurement"},
    {"id": "temp_battery_min", "name": "HV-Batterie Temp Min", "unit": "°C", "dc": "temperature", "icon": "mdi:thermometer-low", "sc": "measurement"},
    {"id": "temp_battery_max", "name": "HV-Batterie Temp Max", "unit": "°C", "dc": "temperature", "icon": "mdi:thermometer-high", "sc": "measurement"},
    # === Inspektion / Wartung ===
    {"id": "inspection_days", "name": "Inspektion fällig in", "unit": "d", "dc": None, "icon": "mdi:wrench-clock", "sc": None},
    # === Parkposition ===
    {"id": "park_latitude", "name": "Parkposition Breitengrad", "unit": "°", "dc": None, "icon": "mdi:crosshairs-gps", "sc": None},
    {"id": "park_longitude", "name": "Parkposition Längengrad", "unit": "°", "dc": None, "icon": "mdi:crosshairs-gps", "sc": None},
    # === Fahrzeugtyp / Status ===
    {"id": "car_type", "name": "Fahrzeugtyp", "unit": None, "dc": None, "icon": "mdi:car", "sc": None},
    {"id": "charging_scenario", "name": "Ladeszenario", "unit": None, "dc": None, "icon": "mdi:calendar-clock", "sc": None},
]


def init(username: str, password: str, vin: str,
         mqtt_host: str = "192.167.178.110",
         mqtt_user: str = "jarvis", mqtt_pass: str = "jarvis-mqtt-2026"):
    global _api, _vin, _mqtt
    _vin = vin
    try:
        _api = weconnect.WeConnect(username=username, password=password, updateAfterLogin=False)
        _api.login()
        _log.info("[vw] Login OK — VIN %s", vin)
    except Exception as e:
        _log.error("[vw] Login fehlgeschlagen: %s", e)
        _api = None

    # MQTT Verbindung
    try:
        _mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="jarvis-vw")
        _mqtt.username_pw_set(mqtt_user, mqtt_pass)
        _mqtt.connect(mqtt_host, 1883, 60)
        _mqtt.loop_start()
        print(f"[vw] MQTT verbunden: {mqtt_host}", flush=True)
    except Exception as e:
        print(f"[vw] MQTT Fehler: {e}", flush=True)
        _mqtt = None


def _publish_discovery():
    """MQTT Autodiscovery Config an HA senden."""
    global _mqtt_discovery_sent
    if not _mqtt or _mqtt_discovery_sent:
        return

    device = {
        "identifiers": [f"vw_{_vin}"],
        "name": "VW ID.7",
        "manufacturer": "Volkswagen",
        "model": "ID.7",
        "sw_version": "WeConnect API",
    }

    for s in ALL_SENSORS:
        config = {
            "name": f"VW ID.7 {s['name']}",
            "state_topic": f"jarvis/vw/{_vin}/{s['id']}",
            "unique_id": f"vw_{_vin}_{s['id']}",
            "device": device,
            "icon": s["icon"],
        }
        if s["unit"]:
            config["unit_of_measurement"] = s["unit"]
        if s["dc"]:
            config["device_class"] = s["dc"]
        if s["sc"]:
            config["state_class"] = s["sc"]

        disc_topic = f"homeassistant/sensor/vw_{_vin}_{s['id']}/config"
        _mqtt.publish(disc_topic, json.dumps(config), retain=True)

    _mqtt_discovery_sent = True
    print(f"[vw] MQTT Autodiscovery gesendet ({len(ALL_SENSORS)} Sensoren)", flush=True)


def _enum_str(val):
    """Enum-Wert zu lesbarem String."""
    s = str(val)
    return s.split(".")[-1].replace("_", " ") if "." in s else s


def _kelvin_to_celsius(k):
    """Kelvin zu Celsius."""
    try:
        return round(float(k) - 273.15, 1)
    except (TypeError, ValueError):
        return None


def _safe_val(obj, *attrs):
    """Verschachtelten Attribut-Zugriff mit Fallback."""
    try:
        current = obj
        for a in attrs:
            current = getattr(current, a)
        return current.value if hasattr(current, "value") else current
    except Exception:
        return None


def _collect_all(v) -> dict:
    """Alle Werte aus dem Fahrzeug extrahieren."""
    d = {}

    # === Charging / batteryStatus ===
    bs = _safe_val(v, "domains") or {}
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
        d["charge_type"] = _enum_str(_safe_val(cs, "chargeType"))
        d["charge_mode"] = _enum_str(_safe_val(cs, "chargeMode"))
        d["remaining_charge_time"] = _safe_val(cs, "remainingChargingTimeToComplete_min") or 0
        d["charging_scenario"] = _enum_str(_safe_val(cs, "chargingScenario"))
    except Exception:
        pass

    try:
        csettings = v.domains["charging"]["chargingSettings"]
        d["target_soc"] = _safe_val(csettings, "targetSOC_pct")
        d["max_charge_current"] = _enum_str(_safe_val(csettings, "maxChargeCurrentAC"))
        d["auto_unlock_plug"] = _enum_str(_safe_val(csettings, "autoUnlockPlugWhenCharged"))
    except Exception:
        pass

    try:
        ps = v.domains["charging"]["plugStatus"]
        d["plug_connection"] = _enum_str(_safe_val(ps, "plugConnectionState"))
        d["plug_lock"] = _enum_str(_safe_val(ps, "plugLockState"))
        d["external_power"] = _enum_str(_safe_val(ps, "externalPower"))
        d["led_color"] = _enum_str(_safe_val(ps, "ledColor"))
    except Exception:
        pass

    try:
        care = v.domains["charging"]["chargingCareSettings"]
        d["battery_care"] = _enum_str(_safe_val(care, "batteryCareMode"))
    except Exception:
        try:
            care = v.domains["batteryChargingCare"]["chargingCareSettings"]
            d["battery_care"] = _enum_str(_safe_val(care, "batteryCareMode"))
        except Exception:
            pass

    # === Access ===
    try:
        acc = v.domains["access"]["accessStatus"]
        d["door_lock"] = _enum_str(_safe_val(acc, "doorLockStatus"))
        d["overall_status"] = _enum_str(_safe_val(acc, "overallStatus"))
    except Exception:
        pass

    # === Climatisation ===
    try:
        cl = v.domains["climatisation"]["climatisationStatus"]
        d["climatisation_state"] = _enum_str(_safe_val(cl, "climatisationState"))
        d["climatisation_remaining"] = _safe_val(cl, "remainingClimatisationTime_min") or 0
    except Exception:
        pass

    try:
        cls = v.domains["climatisation"]["climatisationSettings"]
        d["target_temp"] = _safe_val(cls, "targetTemperature_C")
        d["climatise_at_unlock"] = _safe_val(cls, "climatizationAtUnlock")
        d["window_heating"] = _safe_val(cls, "windowHeatingEnabled")
        d["seat_heating_fl"] = _safe_val(cls, "zoneFrontLeftEnabled")
        d["seat_heating_fr"] = _safe_val(cls, "zoneFrontRightEnabled")
    except Exception:
        pass

    # === Measurements / Temperaturen ===
    try:
        to = v.domains["measurements"]["temperatureOutsideStatus"]
        k = _safe_val(to, "temperatureOutside_K")
        d["temp_outside"] = _kelvin_to_celsius(k)
    except Exception:
        pass

    try:
        tb = v.domains["measurements"]["temperatureBatteryStatus"]
        d["temp_battery_min"] = _kelvin_to_celsius(_safe_val(tb, "temperatureHvBatteryMin_K"))
        d["temp_battery_max"] = _kelvin_to_celsius(_safe_val(tb, "temperatureHvBatteryMax_K"))
    except Exception:
        pass

    try:
        odo = v.domains["measurements"]["odometerStatus"]
        d["odometer"] = _safe_val(odo, "odometer")
    except Exception:
        pass

    # === Fuel / Range ===
    try:
        rs = v.domains["fuelStatus"]["rangeStatus"]
        d["car_type"] = _enum_str(_safe_val(rs, "carType"))
    except Exception:
        pass

    # === Inspektion ===
    try:
        maint = v.domains["vehicleHealthInspection"]["maintenanceStatus"]
        d["inspection_days"] = _safe_val(maint, "inspectionDue_days")
    except Exception:
        pass

    # === Parkposition ===
    try:
        park = v.domains["parking"]["parkingPosition"]
        d["park_latitude"] = _safe_val(park, "latitude")
        d["park_longitude"] = _safe_val(park, "longitude")
    except Exception:
        pass

    return d


def _publish_values(data: dict):
    """Sensor-Werte per MQTT publishen."""
    if not _mqtt:
        return
    base = f"jarvis/vw/{_vin}"
    for key, value in data.items():
        if value is not None:
            _mqtt.publish(f"{base}/{key}", str(value), retain=True)


def get_telemetry() -> list[str]:
    """Aktuelle Fahrzeugdaten als HUD-Zeilen + MQTT publish."""
    if not _api or not _vin:
        return []

    _publish_discovery()

    lines = []
    try:
        _api.update()
        v = _api.vehicles[_vin]
        data = _collect_all(v)
        _publish_values(data)

        # HUD Terminal Zeilen (nur die wichtigsten)
        if data.get("soc") is not None:
            lines.append(f"VW ID.7 SOC: {data['soc']}%")
        if data.get("range") is not None:
            lines.append(f"VW ID.7 RANGE: {data['range']} KM")
        cp = data.get("charge_power")
        if cp and float(cp) > 0:
            lines.append(f"VW ID.7 CHARGING: {cp} KW")
        else:
            cs = data.get("charging_state", "")
            if cs:
                lines.append(f"VW ID.7 STATUS: {cs}")
        if data.get("odometer") is not None:
            lines.append(f"VW ID.7 ODOMETER: {data['odometer']} KM")

    except Exception as e:
        _log.warning("[vw] Update error: %s", e)
        try:
            _api.login()
        except Exception:
            pass
    return lines
