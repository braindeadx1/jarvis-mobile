"""
Jarvis Mobile — Home Assistant Integration
REST API fuer Befehle, WebSocket fuer Live-Status-Updates.
Entitaeten werden aus devices.csv geladen (erweiterbar per Excel/CSV).
"""

import asyncio
import csv
import json
import os
import re
from dataclasses import dataclass, field

import httpx

# ---------------------------------------------------------------------------
# Device Registry (aus devices.csv)
# ---------------------------------------------------------------------------
@dataclass
class Device:
    entity_id: str
    friendly_name: str
    room: str
    type: str
    watch: bool
    notes: str = ""


class DeviceRegistry:
    """Laedt und verwaltet Geraete aus devices.csv."""

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.devices: list[Device] = []
        self.by_id: dict[str, Device] = {}
        self.by_room: dict[str, list[Device]] = {}
        self.watched: list[Device] = []
        self.reload()

    def reload(self):
        """CSV neu laden (hot-reload moeglich)."""
        self.devices = []
        self.by_id = {}
        self.by_room = {}
        self.watched = []

        if not os.path.exists(self.csv_path):
            print("[ha] WARNUNG: devices.csv nicht gefunden!", flush=True)
            return

        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("entity_id") or row["entity_id"].startswith("#"):
                    continue
                dev = Device(
                    entity_id=row["entity_id"].strip(),
                    friendly_name=row.get("friendly_name", "").strip(),
                    room=row.get("room", "").strip(),
                    type=row.get("type", "").strip(),
                    watch=row.get("watch", "").strip().lower() == "yes",
                    notes=row.get("notes", "").strip(),
                )
                self.devices.append(dev)
                self.by_id[dev.entity_id] = dev
                self.by_room.setdefault(dev.room, []).append(dev)
                if dev.watch:
                    self.watched.append(dev)

        print(f"[ha] {len(self.devices)} Geraete geladen, {len(self.watched)} ueberwacht", flush=True)

    def find(self, query: str) -> list[Device]:
        """Suche nach Geraet per Name, Raum oder Entity-ID (fuzzy)."""
        q = query.lower()
        results = []
        for dev in self.devices:
            if q in dev.entity_id.lower() or q in dev.friendly_name.lower() or q in dev.room.lower():
                results.append(dev)
        return results

    def get_rooms(self) -> list[str]:
        """Alle Raeume zurueckgeben."""
        return sorted(self.by_room.keys())

    def get_room_devices(self, room: str) -> list[Device]:
        """Geraete eines Raumes zurueckgeben."""
        for r, devs in self.by_room.items():
            if room.lower() in r.lower():
                return devs
        return []


# ---------------------------------------------------------------------------
# Home Assistant Client
# ---------------------------------------------------------------------------
class HomeAssistantClient:
    """REST + WebSocket Client fuer Home Assistant."""

    def __init__(self, url: str, token: str, registry: DeviceRegistry):
        self.base_url = url.rstrip("/")
        self.token = token
        self.registry = registry
        self.http = httpx.AsyncClient(
            timeout=10,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        self._ws_task: asyncio.Task | None = None
        self._ws_callbacks: list = []
        self._ws_id_counter = 0

    # --- REST API ---

    async def get_state(self, entity_id: str) -> dict | None:
        """Einzelnen Entitaets-Status abfragen."""
        try:
            resp = await self.http.get(f"{self.base_url}/api/states/{entity_id}")
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception as e:
            print(f"[ha] Fehler bei get_state({entity_id}): {e}", flush=True)
            return None

    async def get_states(self, entity_ids: list[str]) -> list[dict]:
        """Mehrere Entitaets-Status abfragen."""
        tasks = [self.get_state(eid) for eid in entity_ids]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def call_service(self, domain: str, service: str, entity_id: str, **kwargs) -> bool:
        """HA Service aufrufen (z.B. light.turn_on)."""
        data = {"entity_id": entity_id, **kwargs}
        try:
            resp = await self.http.post(
                f"{self.base_url}/api/services/{domain}/{service}",
                json=data,
            )
            ok = resp.status_code == 200
            print(f"[ha] {domain}.{service}({entity_id}) -> {'OK' if ok else resp.status_code}", flush=True)
            return ok
        except Exception as e:
            print(f"[ha] Service-Fehler: {e}", flush=True)
            return False

    # --- Komfort-Methoden ---

    async def turn_on(self, entity_id: str, **kwargs) -> bool:
        domain = entity_id.split(".")[0]
        if domain == "cover":
            return await self.call_service("cover", "open_cover", entity_id, **kwargs)
        return await self.call_service(domain, "turn_on", entity_id, **kwargs)

    async def turn_off(self, entity_id: str) -> bool:
        domain = entity_id.split(".")[0]
        if domain == "cover":
            return await self.call_service("cover", "close_cover", entity_id)
        return await self.call_service(domain, "turn_off", entity_id)

    async def toggle(self, entity_id: str) -> bool:
        domain = entity_id.split(".")[0]
        if domain == "cover":
            return await self.call_service("cover", "toggle", entity_id)
        return await self.call_service(domain, "toggle", entity_id)

    async def set_temperature(self, entity_id: str, temperature: float) -> bool:
        return await self.call_service("climate", "set_temperature", entity_id, temperature=temperature)

    async def set_cover_position(self, entity_id: str, position: int) -> bool:
        return await self.call_service("cover", "set_cover_position", entity_id, position=position)

    # --- Uebersicht-Methoden ---

    async def get_room_status(self, room: str) -> str:
        """Status aller Geraete eines Raumes als Text."""
        devices = self.registry.get_room_devices(room)
        if not devices:
            return f"Raum '{room}' nicht gefunden."

        lines = [f"=== {room} ==="]
        states = await self.get_states([d.entity_id for d in devices])
        state_map = {s["entity_id"]: s for s in states}

        for dev in devices:
            s = state_map.get(dev.entity_id)
            if not s:
                continue
            state = s["state"]
            attrs = s.get("attributes", {})

            if dev.type == "climate":
                current = attrs.get("current_temperature", "?")
                target = attrs.get("temperature", "?")
                lines.append(f"  {dev.friendly_name}: {current}°C (Soll: {target}°C)")
            elif dev.type == "temperature":
                lines.append(f"  {dev.friendly_name}: {state}°C")
            elif dev.type in ("light", "light_group", "switch"):
                lines.append(f"  {dev.friendly_name}: {'AN' if state == 'on' else 'AUS'}")
            elif dev.type == "cover":
                pos = attrs.get("current_position", "?")
                lines.append(f"  {dev.friendly_name}: {state} ({pos}%)")
            else:
                lines.append(f"  {dev.friendly_name}: {state}")

        return "\n".join(lines)

    async def get_all_temperatures(self) -> str:
        """Alle Raumtemperaturen als Uebersicht."""
        temp_devices = [d for d in self.registry.devices if d.type == "temperature" and d.watch]
        if not temp_devices:
            return "Keine Temperatursensoren konfiguriert."

        states = await self.get_states([d.entity_id for d in temp_devices])
        state_map = {s["entity_id"]: s for s in states}

        lines = ["Raumtemperaturen:"]
        for dev in temp_devices:
            s = state_map.get(dev.entity_id)
            if s and s["state"] not in ("unavailable", "unknown"):
                lines.append(f"  {dev.room}: {s['state']}°C")

        return "\n".join(lines)

    async def get_house_overview(self) -> str:
        """Ueberblick: was laeuft gerade im Haus?"""
        all_states = await self.get_states([d.entity_id for d in self.registry.devices])
        state_map = {s["entity_id"]: s for s in all_states}

        lights_on = []
        covers_closed = []
        climate_info = []
        doors_open = []
        alerts = []

        for dev in self.registry.devices:
            s = state_map.get(dev.entity_id)
            if not s:
                continue
            state = s["state"]
            attrs = s.get("attributes", {})

            if dev.type in ("light", "light_group") and state == "on":
                lights_on.append(dev.friendly_name)
            elif dev.type == "cover" and state == "closed":
                covers_closed.append(dev.friendly_name)
            elif dev.type == "climate":
                current = attrs.get("current_temperature", "?")
                lights_on  # just to reference
                climate_info.append(f"{dev.room}: {current}°C")
            elif dev.type in ("door", "window") and state == "on":
                doors_open.append(dev.friendly_name)
            elif dev.type == "water" and state == "on":
                alerts.append(f"WASSER-ALARM: {dev.friendly_name}!")
            elif dev.type == "security" and state == "on":
                alerts.append(f"Bewegung: {dev.friendly_name}")

        lines = []
        if alerts:
            lines.append("ALARME: " + ", ".join(alerts))
        if lights_on:
            lines.append(f"Lichter an ({len(lights_on)}): " + ", ".join(lights_on))
        if doors_open:
            lines.append(f"Offen: " + ", ".join(doors_open))
        if climate_info:
            lines.append("Temperaturen: " + ", ".join(climate_info))
        if covers_closed:
            lines.append(f"Rolladen zu: " + ", ".join(covers_closed))

        if not lines:
            lines.append("Alles ruhig im Haus.")

        return "\n".join(lines)

    async def goodnight(self) -> list[str]:
        """Gute-Nacht-Routine: Lichter aus, Rolladen zu."""
        actions = []

        # Alle Lichter und Licht-Gruppen aus
        for dev in self.registry.devices:
            if dev.type in ("light", "light_group"):
                state = await self.get_state(dev.entity_id)
                if state and state["state"] == "on":
                    await self.turn_off(dev.entity_id)
                    actions.append(f"{dev.friendly_name} ausgeschaltet")

        # Alle Rolladen schliessen
        for dev in self.registry.devices:
            if dev.type == "cover":
                state = await self.get_state(dev.entity_id)
                if state and state["state"] == "open":
                    await self.turn_off(dev.entity_id)
                    actions.append(f"{dev.friendly_name} geschlossen")

        # Aussensteckdosen aus
        for dev in self.registry.devices:
            if dev.room == "Aussenanlagen" and dev.type == "switch":
                state = await self.get_state(dev.entity_id)
                if state and state["state"] == "on":
                    await self.turn_off(dev.entity_id)
                    actions.append(f"{dev.friendly_name} ausgeschaltet")

        return actions if actions else ["Alles war bereits aus."]

    # --- WebSocket Live-Updates ---

    def on_state_change(self, callback):
        """Callback registrieren fuer Statusaenderungen.
        callback(entity_id: str, old_state: str, new_state: str, attributes: dict)
        """
        self._ws_callbacks.append(callback)

    async def start_websocket(self):
        """WebSocket-Verbindung zu HA fuer Live-Updates starten."""
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self):
        """WebSocket Event-Loop — reconnect bei Verbindungsabbruch."""
        import websockets

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"

        while True:
            try:
                async with websockets.connect(ws_url) as ws:
                    # Auth
                    msg = json.loads(await ws.recv())
                    if msg.get("type") == "auth_required":
                        await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                        auth_result = json.loads(await ws.recv())
                        if auth_result.get("type") != "auth_ok":
                            print(f"[ha-ws] Auth fehlgeschlagen: {auth_result}", flush=True)
                            await asyncio.sleep(10)
                            continue

                    print("[ha-ws] Verbunden und authentifiziert", flush=True)

                    # Nur ueberwachte Entitaeten subscriben
                    watched_ids = [d.entity_id for d in self.registry.watched]
                    if not watched_ids:
                        print("[ha-ws] Keine Geraete zum Ueberwachen.", flush=True)
                        await asyncio.sleep(60)
                        continue

                    self._ws_id_counter += 1
                    await ws.send(json.dumps({
                        "id": self._ws_id_counter,
                        "type": "subscribe_events",
                        "event_type": "state_changed",
                    }))

                    # Events verarbeiten
                    async for message in ws:
                        data = json.loads(message)
                        if data.get("type") != "event":
                            continue
                        event = data.get("event", {})
                        event_data = event.get("data", {})
                        entity_id = event_data.get("entity_id", "")

                        # Nur ueberwachte Entitaeten
                        if entity_id not in watched_ids:
                            continue

                        old = event_data.get("old_state", {})
                        new = event_data.get("new_state", {})
                        old_state = old.get("state", "") if old else ""
                        new_state = new.get("state", "") if new else ""
                        new_attrs = new.get("attributes", {}) if new else {}

                        if old_state != new_state:
                            dev = self.registry.by_id.get(entity_id)
                            name = dev.friendly_name if dev else entity_id
                            print(f"[ha-ws] {name}: {old_state} -> {new_state}", flush=True)

                            for cb in self._ws_callbacks:
                                try:
                                    await cb(entity_id, old_state, new_state, new_attrs)
                                except Exception as e:
                                    print(f"[ha-ws] Callback-Fehler: {e}", flush=True)

            except Exception as e:
                print(f"[ha-ws] Verbindungsfehler: {e} — Reconnect in 10s", flush=True)
                await asyncio.sleep(10)

    async def stop_websocket(self):
        if self._ws_task:
            self._ws_task.cancel()
            self._ws_task = None


# ---------------------------------------------------------------------------
# NLP: Sprachbefehl -> HA-Aktion
# ---------------------------------------------------------------------------
def parse_ha_command(text: str, registry: DeviceRegistry) -> dict | None:
    """Versucht einen HA-Befehl aus natuerlichem Text zu extrahieren.
    Gibt dict mit action, entity_id, params zurueck oder None.
    """
    t = text.lower()

    # "alles aus" / "gute nacht" / "ich gehe schlafen"
    if any(p in t for p in ["alles aus", "gute nacht", "ich gehe schlafen", "schlafenszeit"]):
        return {"action": "goodnight"}

    # "was laeuft" / "ueberblick" / "status"
    if any(p in t for p in ["was läuft", "was laeuft", "überblick", "ueberblick", "was ist los", "status zuhause"]):
        return {"action": "overview"}

    # "alle temperaturen" / "wie warm"
    if any(p in t for p in ["alle temperatur", "raumtemperatur", "wie warm ist es überall"]):
        return {"action": "all_temperatures"}

    # Raum-Status: "status wohnzimmer" / "was ist im wohnzimmer"
    for room in registry.get_rooms():
        if room.lower() in t and any(p in t for p in ["status", "was ist", "wie ist"]):
            return {"action": "room_status", "room": room}

    # Temperatur-Abfrage: "wie warm ist es im schlafzimmer"
    temp_match = re.search(r"(?:wie warm|temperatur|wieviel grad).*?(?:im |in der |in |)(\w+)", t)
    if temp_match:
        room_query = temp_match.group(1)
        devices = registry.find(room_query)
        temp_devs = [d for d in devices if d.type == "temperature"]
        if temp_devs:
            return {"action": "get_temperature", "entity_id": temp_devs[0].entity_id, "room": temp_devs[0].room}

    # Licht/Schalter steuern
    action = None
    if any(p in t for p in ["mach an", "schalte an", "einschalten", "anmachen", "turn on", "licht an"]):
        action = "turn_on"
    elif any(p in t for p in ["mach aus", "schalte aus", "ausschalten", "ausmachen", "turn off", "licht aus"]):
        action = "turn_off"
    elif any(p in t for p in ["umschalten", "toggle", "wechsel"]):
        action = "toggle"

    # Rolladen
    if any(p in t for p in ["rolladen hoch", "rolladen auf", "rollladen hoch", "rollladen auf"]):
        action = "turn_on"  # open_cover
    elif any(p in t for p in ["rolladen runter", "rolladen zu", "rollladen runter", "rollladen zu"]):
        action = "turn_off"  # close_cover

    # Heizung
    temp_set = re.search(r"(?:heizung|temperatur).*?auf (\d+(?:[.,]\d+)?)", t)
    if temp_set:
        target = float(temp_set.group(1).replace(",", "."))
        # Raum finden
        for room in registry.get_rooms():
            if room.lower() in t:
                climate_devs = [d for d in registry.get_room_devices(room) if d.type == "climate"]
                if climate_devs:
                    return {"action": "set_temperature", "entity_id": climate_devs[0].entity_id, "temperature": target, "room": room}

    if action:
        # Geraet finden
        for dev in registry.devices:
            if dev.type in ("light", "light_group", "switch", "cover"):
                name_lower = dev.friendly_name.lower()
                room_lower = dev.room.lower()
                # Pruefe ob Raum oder Name im Text vorkommt
                if room_lower in t and (dev.type in t or "licht" in t or "rolladen" in t or "rollladen" in t or name_lower in t):
                    return {"action": action, "entity_id": dev.entity_id}
                if name_lower in t:
                    return {"action": action, "entity_id": dev.entity_id}

        # Fallback: Raum + Typ-Matching
        for room in registry.get_rooms():
            if room.lower() in t:
                room_devs = registry.get_room_devices(room)
                if "licht" in t or "light" in t:
                    light_devs = [d for d in room_devs if d.type in ("light", "light_group")]
                    if light_devs:
                        return {"action": action, "entity_id": light_devs[0].entity_id}
                if "rolladen" in t or "rollladen" in t:
                    cover_devs = [d for d in room_devs if d.type == "cover"]
                    if cover_devs:
                        return {"action": action, "entity_id": cover_devs[0].entity_id}
                # Default: erstes schaltbares Geraet im Raum
                switchable = [d for d in room_devs if d.type in ("light", "light_group", "switch")]
                if switchable:
                    return {"action": action, "entity_id": switchable[0].entity_id}

    return None
