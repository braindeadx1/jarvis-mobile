#!/usr/bin/env python3
"""
Jarvis Bridge — Ueberwacht ClawBot Session-Logs auf Bot-Antworten
und leitet sie an Jarvis Mobile zum Vorlesen weiter.
Smarthome-Meldungen (Fenster, etc.) werden mit Cooldown gefiltert.
Laeuft als Service auf CT 7200 (ClawBot).
"""
import json
import os
import re
import ssl
import time
import urllib.request

JARVIS_URL = "https://192.167.200.30:8443/webhook/clawbot"
JARVIS_SECRET = "jarvis-secret-2026"
SESSIONS_DIR = "/root/.clawdbot/agents/main/sessions"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

seen_ids = set()

# ---------------------------------------------------------------------------
# Cooldown-Filter fuer Smarthome-Meldungen
# ---------------------------------------------------------------------------
# Muster die als Smarthome-Meldung erkannt werden + Cooldown in Sekunden
COOLDOWN_RULES = [
    # (regex_pattern, cooldown_seconds)
    (r"wasser.?alarm|wassersensor|wassermelder", 0),        # Wasser: IMMER
    (r"klingel|doorbell", 30),                                # Klingel: 30s
    (r"person\s*(erkannt|detected)|bewegung.*kamera", 300),   # Person: 5 Min
    (r"fenster|window|t.r.*(offen|geschlossen|ge.ffnet)", 300),  # Fenster/Tuer: 5 Min
    (r"temperatur.*gefallen|temperatur.*erreicht|°C.*alarm", 1800),  # Temp: 30 Min
]

# Schluesselwoerter die eine Smarthome-Meldung identifizieren
SMARTHOME_KEYWORDS = [
    "fenster", "window", "geöffnet", "geschlossen", "offen",
    "tür", "türe", "klingel", "bewegung", "person erkannt",
    "temperatur", "°C", "alarm", "sensor",
    "✅", "🪟", "🚪", "🔔", "🌡",  # Typische Emojis in HA-Meldungen
]

_cooldown_tracker: dict[str, float] = {}


def _is_smarthome_message(text: str) -> bool:
    """Prueft ob eine Nachricht eine automatische Smarthome-Meldung ist."""
    t = text.lower()
    matches = sum(1 for kw in SMARTHOME_KEYWORDS if kw.lower() in t)
    return matches >= 2  # Mindestens 2 Keywords = Smarthome-Meldung


def _get_cooldown_key(text: str) -> str:
    """Erzeugt einen Gruppierungsschluessel fuer aehnliche Meldungen.
    'Arbeitszimmer Fenster geöffnet' und 'Arbeitszimmer Fenster geschlossen'
    werden zur gleichen Gruppe."""
    t = text.lower()
    # Raum + Geraet extrahieren
    words = re.findall(r'[a-zäöüß]+', t)
    # Raumnamen und Geraetetypen als Key
    rooms = ["wohnzimmer", "esszimmer", "küche", "kueche", "arbeitszimmer",
             "schlafzimmer", "kinderzimmer", "treppenhaus", "keller",
             "wintergarten", "badezimmer", "gäste", "gaeste", "garage",
             "eingang", "dachboden"]
    devices = ["fenster", "tür", "türe", "klingel", "sensor", "temperatur",
               "rolladen", "licht", "wasser"]
    key_parts = []
    for w in words:
        if w in rooms or w in devices:
            key_parts.append(w)
    return ":".join(key_parts) if key_parts else text[:50]


def _check_cooldown(text: str) -> bool:
    """Prueft Cooldown fuer Smarthome-Meldungen.
    Gibt True zurueck wenn die Nachricht weitergeleitet werden soll."""
    t = text.lower()

    # Cooldown-Regel finden
    cooldown = 300  # Default: 5 Min
    for pattern, cd in COOLDOWN_RULES:
        if re.search(pattern, t):
            cooldown = cd
            break

    # Wasser-Alarm: kein Cooldown
    if cooldown == 0:
        return True

    key = _get_cooldown_key(text)
    now = time.time()
    last = _cooldown_tracker.get(key, 0)

    if now - last < cooldown:
        print(f"[bridge] Cooldown aktiv ({key}), uebersprungen", flush=True)
        return False

    _cooldown_tracker[key] = now

    # Alte Eintraege bereinigen
    if len(_cooldown_tracker) > 200:
        cutoff = now - 3600
        _cooldown_tracker.clear()

    return True


# ---------------------------------------------------------------------------
# Jarvis Weiterleitung
# ---------------------------------------------------------------------------
def forward_to_jarvis(sender_name, channel, message):
    payload = json.dumps({
        "secret": JARVIS_SECRET,
        "sender": "Friday",
        "sender_name": sender_name,
        "channel": channel,
        "message": message
    }).encode()
    try:
        req = urllib.request.Request(
            JARVIS_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=10, context=ssl_ctx)
        print(f"[bridge] -> Jarvis: {message[:80]}", flush=True)
    except Exception as e:
        print(f"[bridge] Jarvis Fehler: {e}", flush=True)


# ---------------------------------------------------------------------------
# Session Monitoring
# ---------------------------------------------------------------------------
def get_active_session():
    """Findet die aktive Session-JSONL-Datei."""
    try:
        sessions_file = os.path.join(SESSIONS_DIR, "sessions.json")
        if os.path.exists(sessions_file):
            with open(sessions_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for sid, info in data.items():
                    jsonl = os.path.join(SESSIONS_DIR, f"{sid}.jsonl")
                    if os.path.exists(jsonl):
                        return jsonl

        # Fallback: neueste .jsonl Datei
        jsonls = [f for f in os.listdir(SESSIONS_DIR) if f.endswith(".jsonl") and "deleted" not in f]
        if jsonls:
            jsonls.sort(key=lambda f: os.path.getmtime(os.path.join(SESSIONS_DIR, f)), reverse=True)
            return os.path.join(SESSIONS_DIR, jsonls[0])
    except Exception as e:
        print(f"[bridge] Session-Fehler: {e}", flush=True)
    return None


def extract_reply(line):
    """Extrahiert Bot-Antwort-Text aus einer JSONL-Zeile."""
    try:
        data = json.loads(line)
    except Exception:
        return None

    if data.get("type") != "message":
        return None

    msg = data.get("message", {})
    if msg.get("role") != "assistant":
        return None

    msg_id = data.get("id", "")
    if msg_id in seen_ids:
        return None

    content = msg.get("content", [])
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text", "")
                if t in ("NO_REPLY", "HEARTBEAT_OK", ""):
                    return None
                texts.append(t)
        text = " ".join(texts)
    else:
        return None

    if not text or len(text) < 3:
        return None

    seen_ids.add(msg_id)
    return text


def tail_session(filepath):
    """Tailed eine JSONL-Datei und gibt neue Zeilen zurueck."""
    with open(filepath, "r") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                yield line.strip()
            else:
                time.sleep(0.5)


def run():
    print("[bridge] Jarvis Bridge gestartet (Session-Monitor + Cooldown)", flush=True)
    print(f"[bridge] Jarvis: {JARVIS_URL}", flush=True)
    print(f"[bridge] Sessions: {SESSIONS_DIR}", flush=True)

    current_file = None

    while True:
        session = get_active_session()
        if not session:
            print("[bridge] Keine aktive Session gefunden, warte...", flush=True)
            time.sleep(10)
            continue

        if session != current_file:
            current_file = session
            print(f"[bridge] Ueberwache: {os.path.basename(session)}", flush=True)

        try:
            for line in tail_session(session):
                reply = extract_reply(line)
                if reply:
                    # Smarthome-Meldung? → Cooldown pruefen
                    if _is_smarthome_message(reply):
                        if not _check_cooldown(reply):
                            continue  # Cooldown aktiv, nicht weiterleiten
                        print(f"[bridge] Smarthome-Meldung: {reply[:80]}", flush=True)
                    else:
                        print(f"[bridge] Bot-Antwort: {reply[:80]}", flush=True)

                    forward_to_jarvis("ClawBot", "whatsapp", reply)

                new_session = get_active_session()
                if new_session and new_session != session:
                    print(f"[bridge] Neue Session: {os.path.basename(new_session)}", flush=True)
                    break

        except Exception as e:
            print(f"[bridge] Fehler: {e}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
