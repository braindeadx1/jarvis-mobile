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


def init(username: str, password: str, vin: str, mqtt_host: str = "192.167.178.110"):
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

    sensors = [
        {
            "id": "soc",
            "name": "VW ID.7 Ladestand",
            "topic": f"jarvis/vw/{_vin}/soc",
            "unit": "%",
            "device_class": "battery",
            "icon": "mdi:car-electric",
        },
        {
            "id": "range",
            "name": "VW ID.7 Reichweite",
            "topic": f"jarvis/vw/{_vin}/range",
            "unit": "km",
            "device_class": None,
            "icon": "mdi:map-marker-distance",
        },
        {
            "id": "charging_state",
            "name": "VW ID.7 Ladestatus",
            "topic": f"jarvis/vw/{_vin}/charging_state",
            "unit": None,
            "device_class": None,
            "icon": "mdi:ev-station",
        },
        {
            "id": "charge_power",
            "name": "VW ID.7 Ladeleistung",
            "topic": f"jarvis/vw/{_vin}/charge_power",
            "unit": "kW",
            "device_class": "power",
            "icon": "mdi:flash",
        },
        {
            "id": "odometer",
            "name": "VW ID.7 Kilometerstand",
            "topic": f"jarvis/vw/{_vin}/odometer",
            "unit": "km",
            "device_class": "distance",
            "icon": "mdi:counter",
        },
    ]

    for s in sensors:
        config = {
            "name": s["name"],
            "state_topic": s["topic"],
            "unique_id": f"vw_{_vin}_{s['id']}",
            "device": device,
            "icon": s["icon"],
        }
        if s["unit"]:
            config["unit_of_measurement"] = s["unit"]
        if s["device_class"]:
            config["device_class"] = s["device_class"]
        if s["id"] != "charging_state":
            config["state_class"] = "measurement"

        disc_topic = f"homeassistant/sensor/vw_{_vin}_{s['id']}/config"
        _mqtt.publish(disc_topic, json.dumps(config), retain=True)

    _mqtt_discovery_sent = True
    print(f"[vw] MQTT Autodiscovery gesendet ({len(sensors)} Sensoren)", flush=True)


def _publish_values(data: dict):
    """Sensor-Werte per MQTT publishen."""
    if not _mqtt:
        return
    base = f"jarvis/vw/{_vin}"
    for key, value in data.items():
        _mqtt.publish(f"{base}/{key}", str(value), retain=True)


def get_telemetry() -> list[str]:
    """Aktuelle Fahrzeugdaten als HUD-Zeilen + MQTT publish."""
    if not _api or not _vin:
        return []

    _publish_discovery()

    lines = []
    mqtt_data = {}
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
            mqtt_data["soc"] = soc
            mqtt_data["range"] = rng
        except Exception:
            pass

        # Charging
        try:
            cs = v.domains["charging"]["chargingStatus"]
            state = cs.chargingState.value
            state_str = str(state).split(".")[-1].replace("_", " ")
            power = cs.chargePower_kW.value
            mqtt_data["charging_state"] = state_str
            mqtt_data["charge_power"] = power if power else 0
            if power and float(power) > 0:
                lines.append(f"VW ID.7 CHARGING: {power} KW")
            else:
                lines.append(f"VW ID.7 STATUS: {state_str}")
        except Exception:
            pass

        # Odometer
        try:
            ms = v.domains["measurements"]["odometerStatus"]
            odo = ms.odometer.value
            lines.append(f"VW ID.7 ODOMETER: {odo} KM")
            mqtt_data["odometer"] = odo
        except Exception:
            pass

        _publish_values(mqtt_data)

    except Exception as e:
        _log.warning("[vw] Update error: %s", e)
        try:
            _api.login()
        except Exception:
            pass
    return lines
