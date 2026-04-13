"""
Jarvis Mobile — Voice AI Server fuer Android PWA
FastAPI backend: LLM via OpenRouter, Edge TTS, Web-Suche,
Home Assistant Steuerung, ClawBot Webhook-Empfaenger.
"""

import asyncio
import base64
import json
import os
import re
import time

import edge_tts
import httpx
from openai import AsyncOpenAI
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from home_assistant import HomeAssistantClient, DeviceRegistry, parse_ha_command

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

LLM_BASE_URL = config.get("llm_base_url", "https://openrouter.ai/api/v1")
LLM_API_KEY = config["llm_api_key"]
LLM_MODEL = config.get("llm_model", "openai/gpt-4o-mini")
ELEVENLABS_API_KEY = config.get("elevenlabs_api_key", "")
ELEVENLABS_VOICE_ID = config.get("elevenlabs_voice_id", "")
TTS_PROVIDER = config.get("tts_provider", "edge").lower()
EDGE_VOICE = config.get("edge_voice", "de-DE-ConradNeural")
USER_NAME = config.get("user_name", "Micha")
USER_ADDRESS = config.get("user_address", "Sir")
CITY = config.get("city", "Dortmund")

# Home Assistant
HA_URL = config.get("ha_url", "")
HA_TOKEN = config.get("ha_token", "")

# ClawBot Webhook
CLAWBOT_WEBHOOK_SECRET = config.get("clawbot_webhook_secret", "jarvis-secret-2026")

# ---------------------------------------------------------------------------
# Verfuegbare LLM-Modelle (mit OpenRouter-Preisen pro Million Tokens)
# ---------------------------------------------------------------------------
AVAILABLE_MODELS = [
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "input": 0.15, "output": 0.60, "tier": "budget"},
    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "input": 0.15, "output": 0.60, "tier": "budget"},
    {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "input": 0.20, "output": 0.60, "tier": "budget"},
    {"id": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "input": 0.40, "output": 1.60, "tier": "mid"},
    {"id": "anthropic/claude-3.5-haiku", "name": "Claude Haiku 3.5", "input": 0.80, "output": 4.00, "tier": "mid"},
    {"id": "anthropic/claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5", "input": 0.80, "output": 4.00, "tier": "mid"},
    {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "input": 1.25, "output": 10.00, "tier": "mid"},
    {"id": "openai/gpt-4.1", "name": "GPT-4.1", "input": 2.00, "output": 8.00, "tier": "premium"},
    {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "input": 3.00, "output": 15.00, "tier": "premium"},
    {"id": "anthropic/claude-opus-4", "name": "Claude Opus 4", "input": 15.00, "output": 75.00, "tier": "premium"},
]

# Aktives Modell pro Session (session_id -> model_id)
session_models: dict[str, str] = {}

# OpenRouter headers
_llm_headers = {}
if "openrouter.ai" in LLM_BASE_URL:
    _llm_headers = {
        "HTTP-Referer": "https://github.com/braindeadx1/jarvis-mobile",
        "X-Title": "Jarvis Mobile",
    }

ai = AsyncOpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    default_headers=_llm_headers or None,
)
http = httpx.AsyncClient(timeout=30)

print(f"[jarvis] LLM: {LLM_MODEL} @ {LLM_BASE_URL}", flush=True)

# ---------------------------------------------------------------------------
# Home Assistant Init
# ---------------------------------------------------------------------------
registry = DeviceRegistry(os.path.join(BASE_DIR, "devices.csv"))
ha: HomeAssistantClient | None = None

if HA_URL and HA_TOKEN:
    ha = HomeAssistantClient(HA_URL, HA_TOKEN, registry)
    print(f"[jarvis] Home Assistant: {HA_URL}", flush=True)
else:
    print("[jarvis] Home Assistant: NICHT konfiguriert", flush=True)

# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def get_weather_sync():
    import urllib.request
    try:
        req = urllib.request.Request(
            f"https://wttr.in/{CITY}?format=j1",
            headers={"User-Agent": "curl"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        c = data["current_condition"][0]
        return {
            "temp": c["temp_C"],
            "feels_like": c["FeelsLikeC"],
            "description": c["weatherDesc"][0]["value"],
        }
    except Exception:
        return None


WEATHER_INFO = get_weather_sync()
print(f"[jarvis] Wetter: {WEATHER_INFO}", flush=True)

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
ACTION_PATTERN = re.compile(r"\[ACTION:(\w+)\]\s*(.*?)$", re.DOTALL | re.MULTILINE)


def build_system_prompt():
    weather = ""
    if WEATHER_INFO:
        w = WEATHER_INFO
        weather = (
            f"\nWetter {CITY}: {w['temp']}°C, "
            f"gefuehlt {w['feels_like']}°C, {w['description']}"
        )

    ha_section = ""
    if ha:
        rooms = ", ".join(registry.get_rooms())
        ha_section = f"""

DU KANNST DAS SMARTHOME STEUERN. Du hast Zugriff auf Home Assistant mit folgenden Raeumen: {rooms}.
Wenn der Nutzer etwas steuern will (Licht, Heizung, Rolladen, etc.) sage einfach was du tust — die Steuerung passiert automatisch.
Du kannst: Lichter schalten, Heizung einstellen, Rolladen steuern, Temperaturen abfragen, Hauszustand abfragen.
Bei "Gute Nacht" oder "Alles aus": Alle Lichter aus, Rolladen zu, Aussensteckdosen aus.

AKTIONEN fuer Smarthome:
[ACTION:HA_OVERVIEW] - Haus-Ueberblick geben
[ACTION:HA_TEMPS] - Alle Raumtemperaturen auflisten
[ACTION:HA_ROOM] raumname - Status eines Raumes
"""

    return f"""Du bist Jarvis, der KI-Assistent von Tony Stark aus Iron Man. Dein Dienstherr ist {USER_NAME}. Du sprichst hauptsaechlich Deutsch, darfst aber gerne als witzige Floskeln oder Kommentare ins gut verstaendliche Englische abrutschen - das gibt dir britischen Charme. {USER_NAME} moechte mit "{USER_ADDRESS}" angesprochen und gesiezt werden. Nutze "Sie" als Pronomen — FALSCH: "Sir planen", RICHTIG: "Sie planen, Sir".

Dein Ton ist trocken, sarkastisch und britisch-hoeflich - wie ein Butler der alles gesehen hat und trotzdem loyal bleibt. Du machst subtile, trockene Bemerkungen, bist aber niemals respektlos. Wenn {USER_ADDRESS} eine offensichtliche Frage stellt, darfst du mit elegantem Sarkasmus antworten. Du bist hochintelligent, effizient und immer einen Schritt voraus. Halte deine Antworten kurz - maximal 3 Saetze. Du kommentierst fragwuerdige Entscheidungen hoeflich aber spitz.

WICHTIG: Schreibe NIEMALS Regieanweisungen, Emotionen oder Tags in eckigen Klammern wie [sarcastic] [formal] [amused] [dry] oder aehnliches. Dein Sarkasmus muss REIN durch die Wortwahl kommen. Alles was du schreibst wird laut vorgelesen.

AKTIONEN - Schreibe die passende Aktion ans ENDE deiner Antwort. Der Text VOR der Aktion wird vorgelesen, die Aktion selbst wird still ausgefuehrt.
[ACTION:SEARCH] suchbegriff - Internet durchsuchen und Ergebnisse zusammenfassen
[ACTION:NEWS] - Aktuelle Weltnachrichten abrufen
{ha_section}
Wenn du ein Bild vom Nutzer erhaeltst, beschreibe was du siehst — kurz, praezise, im Jarvis-Stil.

WENN "{USER_NAME}" dich aktiviert, "Jarvis" sagt, oder das Gespraech beginnt:
- Begruesse passend zur Tageszeit (aktuelle Zeit: {time.strftime("%H:%M")})
- Kurze Wetter-Info
- Sei kreativ bei der Begruessung

=== AKTUELLE DATEN ==={weather}
==="""


def extract_action(text: str):
    match = ACTION_PATTERN.search(text)
    if match:
        clean = text[: match.start()].strip()
        return clean, {"type": match.group(1), "payload": match.group(2).strip()}
    return text, None


# ---------------------------------------------------------------------------
# Web Search (DuckDuckGo HTML)
# ---------------------------------------------------------------------------
async def web_search(query: str) -> str:
    try:
        resp = await http.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            follow_redirects=True,
        )
        text = resp.text
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td)>', text, re.DOTALL
        )
        titles = re.findall(
            r'class="result__a"[^>]*>(.*?)</a>', text, re.DOTALL
        )
        results = []
        for i, (title, snippet) in enumerate(zip(titles[:5], snippets[:5])):
            title = re.sub(r"<[^>]+>", "", title).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet).strip()
            if title and snippet:
                results.append(f"{i + 1}. {title}: {snippet}")
        return "\n".join(results) if results else "Keine Ergebnisse gefunden."
    except Exception as e:
        return f"Suche fehlgeschlagen: {e}"


# ---------------------------------------------------------------------------
# TTS (Edge TTS kostenlos / ElevenLabs optional)
# ---------------------------------------------------------------------------
print(f"[jarvis] TTS: {TTS_PROVIDER} (Voice: {EDGE_VOICE if TTS_PROVIDER == 'edge' else ELEVENLABS_VOICE_ID})", flush=True)


async def synthesize_speech(text: str) -> bytes:
    if not text.strip():
        return b""
    if TTS_PROVIDER == "elevenlabs":
        return await _synthesize_elevenlabs(text)
    return await _synthesize_edge(text)


async def _synthesize_edge(text: str) -> bytes:
    try:
        communicate = edge_tts.Communicate(text, EDGE_VOICE)
        audio_parts = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_parts.append(chunk["data"])
        return b"".join(audio_parts)
    except Exception as e:
        print(f"  Edge TTS EXCEPTION: {e}", flush=True)
        return b""


async def _synthesize_elevenlabs(text: str) -> bytes:
    chunks = []
    if len(text) > 250:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        current = ""
        for s in sentences:
            if len(current) + len(s) > 250 and current:
                chunks.append(current.strip())
                current = s
            else:
                current = (current + " " + s).strip()
        if current:
            chunks.append(current.strip())
    else:
        chunks = [text]

    audio_parts = []
    for chunk in chunks:
        try:
            resp = await http.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": chunk,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.85},
                },
            )
            if resp.status_code == 200:
                audio_parts.append(resp.content)
            else:
                print(f"  TTS error: {resp.status_code} {resp.text[:200]}", flush=True)
        except Exception as e:
            print(f"  TTS EXCEPTION: {e}", flush=True)
    return b"".join(audio_parts)


# ---------------------------------------------------------------------------
# Active WebSocket Clients (fuer Push-Notifications)
# ---------------------------------------------------------------------------
active_clients: dict[str, WebSocket] = {}


async def broadcast_notification(text: str, speak: bool = True):
    """Nachricht an alle verbundenen Clients senden (proaktiv)."""
    audio = b""
    if speak:
        audio = await synthesize_speech(text)

    for sid, ws in list(active_clients.items()):
        try:
            await ws.send_json({
                "type": "notification",
                "text": text,
                "audio": base64.b64encode(audio).decode() if audio else "",
            })
        except Exception:
            active_clients.pop(sid, None)


# ---------------------------------------------------------------------------
# HA State Change Handler (proaktive Meldungen)
# ---------------------------------------------------------------------------
# Cooldown: gleiche Entitaet wird erst nach X Sekunden erneut gemeldet
NOTIFICATION_COOLDOWN = 300  # 5 Minuten
_last_notification: dict[str, float] = {}

# Fenster-Meldungen: HA-Schalter der steuert ob Fenster gemeldet werden
FENSTER_MELDUNGEN_ENTITY = "input_boolean.fenster_meldungen"


async def _is_fenster_meldungen_aktiv() -> bool:
    """Prueft ob der HA-Schalter 'Fenster-Meldungen aktiv' eingeschaltet ist."""
    if not ha:
        return False
    state = await ha.get_state(FENSTER_MELDUNGEN_ENTITY)
    return state is not None and state.get("state") == "on"


def _check_cooldown(entity_id: str, cooldown: int = NOTIFICATION_COOLDOWN) -> bool:
    """Prueft ob die Entitaet innerhalb des Cooldowns bereits gemeldet wurde.
    Gibt True zurueck wenn gemeldet werden darf."""
    now = time.time()
    last = _last_notification.get(entity_id, 0)
    if now - last < cooldown:
        return False
    _last_notification[entity_id] = now
    return True


async def on_ha_state_change(entity_id: str, old_state: str, new_state: str, attrs: dict):
    """Wird aufgerufen wenn sich ein ueberwachtes HA-Geraet aendert."""
    dev = registry.by_id.get(entity_id)
    if not dev:
        return

    message = None
    cooldown = NOTIFICATION_COOLDOWN

    # Tuerklingel — kein Cooldown, immer melden
    if dev.type == "security" and "klingel" in dev.friendly_name.lower() and new_state == "on":
        cooldown = 30  # Nur 30s Cooldown bei Klingel
        message = f"{USER_ADDRESS}, es klingelt an der Tuer. Shall I prepare the welcome mat?"

    # Person erkannt (Kameras) — 5 Min Cooldown
    elif dev.type == "security" and "person" in dev.friendly_name.lower() and new_state == "on":
        message = f"{USER_ADDRESS}, Bewegung erkannt: {dev.friendly_name}."

    # Wasser-Alarm! — IMMER melden, kein Cooldown
    elif dev.type == "water" and new_state == "on":
        cooldown = 0
        message = f"ACHTUNG {USER_ADDRESS}! Wasser-Alarm bei {dev.friendly_name}! Das ist definitiv nicht geplant."

    # Fenster/Tueren — NUR wenn HA-Schalter aktiv
    elif dev.type in ("door", "window") and new_state == "on":
        if await _is_fenster_meldungen_aktiv():
            message = f"{USER_ADDRESS}, {dev.friendly_name} wurde geoeffnet."
        else:
            return  # Schalter aus → keine Meldung

    # Temperatur-Alarm (zu kalt/zu warm) — 30 Min Cooldown
    elif dev.type == "climate":
        cooldown = 1800  # 30 Minuten
        current = attrs.get("current_temperature")
        if current and isinstance(current, (int, float)):
            if current < 15:
                message = f"Achtung {USER_ADDRESS}, {dev.room} ist auf {current}°C gefallen. Rather chilly, wouldn't you say?"
            elif current > 23:
                message = f"{USER_ADDRESS}, {dev.room} hat {current}°C erreicht. Etwas tropisch, wenn Sie mich fragen."

    # Aussentemperatur — Frostwarnung + Sonnenschutz
    elif dev.type == "temperature" and entity_id == "sensor.zuhause_wetterstation_temperature":
        cooldown = 3600  # 1 Stunde
        try:
            temp = float(new_state)
            if temp <= 0:
                message = f"Achtung {USER_ADDRESS}, draussen sind es {temp}°C. Das Wasserfass koennte einfrieren! I suggest immediate action."
            elif temp > 24:
                # Sonnenschutz automatisch aktivieren
                if ha:
                    await ha.call_service("automation", "trigger", "automation.sonnenschutz_aktivieren")
                    print("[jarvis] Sonnenschutz automatisch aktiviert", flush=True)
                message = f"{USER_ADDRESS}, es sind {temp}°C draussen. Ich habe den Sonnenschutz aktiviert."
        except (ValueError, TypeError):
            pass

    if message:
        # Cooldown pruefen (Wasser-Alarm umgeht Cooldown)
        if cooldown > 0 and not _check_cooldown(entity_id, cooldown):
            print(f"[jarvis] Cooldown aktiv fuer {dev.friendly_name}, uebersprungen", flush=True)
            return
        print(f"[jarvis] Proaktiv: {message}", flush=True)
        await broadcast_notification(message)


# ---------------------------------------------------------------------------
# Conversation handling
# ---------------------------------------------------------------------------
conversations: dict[str, list] = {}


def _get_model(session_id: str) -> str:
    """Gibt das aktive LLM-Modell fuer eine Session zurueck."""
    return session_models.get(session_id, LLM_MODEL)


async def process_message(
    session_id: str, user_text: str, ws: WebSocket, image_data: str | None = None
):
    if session_id not in conversations:
        conversations[session_id] = []

    current_model = _get_model(session_id)

    # Wetter bei Aktivierung neu laden
    if "jarvis" in user_text.lower() or "aktivier" in user_text.lower():
        global WEATHER_INFO
        WEATHER_INFO = get_weather_sync()

    # --- HA-Befehle direkt verarbeiten (schneller als LLM) ---
    if ha:
        ha_cmd = parse_ha_command(user_text, registry)
        if ha_cmd:
            await ws.send_json({"type": "status", "status": "thinking"})
            ha_result = await execute_ha_command(ha_cmd)
            if ha_result:
                # LLM formuliert die Antwort im Jarvis-Stil
                try:
                    style_resp = await ai.chat.completions.create(
                        model=current_model,
                        max_tokens=200,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    f"Du bist Jarvis, ein trockener britischer Butler. "
                                    f"Formuliere folgende Smarthome-Aktion als kurze, "
                                    f"sarkastische Bestaetigung (1-2 Saetze). "
                                    f"Sprich den Nutzer als {USER_ADDRESS} an. "
                                    f"KEINE Tags in eckigen Klammern."
                                ),
                            },
                            {"role": "user", "content": ha_result},
                        ],
                    )
                    reply = style_resp.choices[0].message.content or ha_result
                except Exception:
                    reply = ha_result

                await ws.send_json({"type": "status", "status": "speaking"})
                audio = await synthesize_speech(reply)
                conversations[session_id].append({"role": "user", "content": user_text})
                conversations[session_id].append({"role": "assistant", "content": reply})
                await ws.send_json({
                    "type": "response",
                    "text": reply,
                    "audio": base64.b64encode(audio).decode() if audio else "",
                })
                await ws.send_json({"type": "status", "status": "idle"})
                return

    # --- Standard LLM-Verarbeitung ---
    if image_data:
        content = [
            {
                "type": "text",
                "text": user_text
                or "Was siehst du auf diesem Bild? Beschreibe es kurz im Jarvis-Stil.",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"},
            },
        ]
    else:
        content = user_text

    conversations[session_id].append({"role": "user", "content": content})
    history = conversations[session_id][-16:]

    await ws.send_json({"type": "status", "status": "thinking"})

    try:
        response = await ai.chat.completions.create(
            model=current_model,
            max_tokens=400,
            messages=[{"role": "system", "content": build_system_prompt()}, *history],
        )
        reply = response.choices[0].message.content or ""
    except Exception as e:
        print(f"  LLM ERROR: {e}", flush=True)
        reply = f"Da scheint etwas schiefgelaufen zu sein, {USER_ADDRESS}. Quite embarrassing."

    print(f"  LLM: {reply[:200]}", flush=True)
    spoken_text, action = extract_action(reply)

    if spoken_text:
        await ws.send_json({"type": "status", "status": "speaking"})
        audio = await synthesize_speech(spoken_text)
        conversations[session_id].append({"role": "assistant", "content": spoken_text})
        await ws.send_json({
            "type": "response",
            "text": spoken_text,
            "audio": base64.b64encode(audio).decode() if audio else "",
        })

    # Aktionen ausfuehren
    if action:
        print(f"  Action: {action['type']} -> {action['payload'][:100]}", flush=True)
        await ws.send_json({"type": "status", "status": "searching"})

        action_result = ""

        if action["type"] == "SEARCH":
            action_result = await web_search(action["payload"])
        elif action["type"] == "NEWS":
            action_result = await web_search("aktuelle nachrichten heute deutschland")
        elif action["type"] == "HA_OVERVIEW" and ha:
            action_result = await ha.get_house_overview()
        elif action["type"] == "HA_TEMPS" and ha:
            action_result = await ha.get_all_temperatures()
        elif action["type"] == "HA_ROOM" and ha:
            action_result = await ha.get_room_status(action["payload"])

        if action_result and "fehlgeschlagen" not in action_result:
            try:
                summary_resp = await ai.chat.completions.create(
                    model=current_model,
                    max_tokens=250,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                f"Du bist Jarvis. Fasse die folgenden Informationen KURZ "
                                f"auf Deutsch zusammen, maximal 3 Saetze, im Jarvis-Stil. "
                                f"Sprich den Nutzer als {USER_ADDRESS} an. "
                                f"KEINE Tags in eckigen Klammern. KEINE ACTION-Tags."
                            ),
                        },
                        {"role": "user", "content": f"Fasse zusammen:\n\n{action_result}"},
                    ],
                )
                summary = summary_resp.choices[0].message.content or ""
                summary, _ = extract_action(summary)
            except Exception:
                summary = action_result
        else:
            summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}. The system seems to be in a mood."

        await ws.send_json({"type": "status", "status": "speaking"})
        audio2 = await synthesize_speech(summary)
        conversations[session_id].append({"role": "assistant", "content": summary})
        await ws.send_json({
            "type": "response",
            "text": summary,
            "audio": base64.b64encode(audio2).decode() if audio2 else "",
        })

    await ws.send_json({"type": "status", "status": "idle"})


async def execute_ha_command(cmd: dict) -> str | None:
    """Fuehrt einen geparsten HA-Befehl aus."""
    if not ha:
        return None

    action = cmd["action"]

    if action == "goodnight":
        actions = await ha.goodnight()
        return "Gute-Nacht-Routine: " + ", ".join(actions)

    elif action == "overview":
        return await ha.get_house_overview()

    elif action == "all_temperatures":
        return await ha.get_all_temperatures()

    elif action == "room_status":
        return await ha.get_room_status(cmd["room"])

    elif action == "get_temperature":
        state = await ha.get_state(cmd["entity_id"])
        if state:
            return f"Temperatur {cmd.get('room', '')}: {state['state']}°C"
        return "Temperatur konnte nicht abgefragt werden."

    elif action == "turn_on":
        dev = registry.by_id.get(cmd["entity_id"])
        name = dev.friendly_name if dev else cmd["entity_id"]
        ok = await ha.turn_on(cmd["entity_id"])
        return f"{name} eingeschaltet." if ok else f"Fehler beim Einschalten von {name}."

    elif action == "turn_off":
        dev = registry.by_id.get(cmd["entity_id"])
        name = dev.friendly_name if dev else cmd["entity_id"]
        ok = await ha.turn_off(cmd["entity_id"])
        return f"{name} ausgeschaltet." if ok else f"Fehler beim Ausschalten von {name}."

    elif action == "toggle":
        dev = registry.by_id.get(cmd["entity_id"])
        name = dev.friendly_name if dev else cmd["entity_id"]
        ok = await ha.toggle(cmd["entity_id"])
        return f"{name} umgeschaltet." if ok else f"Fehler beim Umschalten von {name}."

    elif action == "set_temperature":
        dev = registry.by_id.get(cmd["entity_id"])
        name = dev.friendly_name if dev else cmd["entity_id"]
        ok = await ha.set_temperature(cmd["entity_id"], cmd["temperature"])
        return f"{name} auf {cmd['temperature']}°C gesetzt." if ok else f"Fehler bei {name}."

    return None


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI()

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")


@app.on_event("startup")
async def startup():
    """HA WebSocket starten fuer Live-Updates."""
    if ha:
        ha.on_state_change(on_ha_state_change)
        await ha.start_websocket()
        print("[jarvis] HA WebSocket gestartet — lausche auf Aenderungen", flush=True)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = str(id(ws))
    active_clients[session_id] = ws
    session_models[session_id] = LLM_MODEL  # Default-Modell
    print(f"[jarvis] Client verbunden: {session_id}", flush=True)

    # Verfuegbare Modelle und aktuelles Modell an Client senden
    await ws.send_json({
        "type": "config",
        "models": AVAILABLE_MODELS,
        "current_model": LLM_MODEL,
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "text")

            if msg_type == "model_change":
                new_model = data.get("model", "")
                valid_ids = [m["id"] for m in AVAILABLE_MODELS]
                if new_model in valid_ids:
                    session_models[session_id] = new_model
                    model_name = next(m["name"] for m in AVAILABLE_MODELS if m["id"] == new_model)
                    print(f"  Modell gewechselt: {model_name} ({new_model})", flush=True)
                    await ws.send_json({"type": "model_changed", "model": new_model, "name": model_name})
                else:
                    await ws.send_json({"type": "error", "message": f"Unbekanntes Modell: {new_model}"})
                continue

            if msg_type == "image":
                image_data = data.get("image", "")
                text = data.get("text", "")
                print(f"  Bild empfangen ({len(image_data) // 1024}KB)", flush=True)
                await process_message(session_id, text, ws, image_data=image_data)
            else:
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue
                print(f"  User: {user_text}", flush=True)
                await process_message(session_id, user_text, ws)

    except WebSocketDisconnect:
        active_clients.pop(session_id, None)
        conversations.pop(session_id, None)
        session_models.pop(session_id, None)
        print(f"[jarvis] Client getrennt: {session_id}", flush=True)


# ---------------------------------------------------------------------------
# ClawBot Webhook Endpoint
# ---------------------------------------------------------------------------
@app.post("/webhook/clawbot")
async def clawbot_webhook(request: Request):
    """Empfaengt Nachrichten von ClawBot und leitet sie an Jarvis-Clients weiter.

    ClawBot sendet:
    {
        "secret": "jarvis-secret-2026",
        "sender": "+4915152721601",
        "sender_name": "Micha",
        "channel": "whatsapp",
        "message": "Hey, bin in 10 Min da"
    }
    """
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    # Auth pruefen
    if data.get("secret") != CLAWBOT_WEBHOOK_SECRET:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    sender = data.get("sender_name", data.get("sender", "Unbekannt"))
    channel = data.get("channel", "unknown")
    message = data.get("message", "")

    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    print(f"[clawbot] {channel}/{sender}: {message[:100]}", flush=True)

    # Jarvis formuliert die Benachrichtigung
    try:
        notif_resp = await ai.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=100,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Du bist Jarvis. Deine Kollegin Friday (ein anderer KI-Assistent) "
                        f"hat eine {channel}-Nachricht fuer {USER_ADDRESS} weitergeleitet. "
                        f"Kuendige sie kurz an (1 Satz). Nenne die Quelle 'Friday'. "
                        f"KEINE Tags in eckigen Klammern."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Friday meldet von {sender}: {message}",
                },
            ],
        )
        notification = notif_resp.choices[0].message.content or f"Nachricht von {sender}: {message}"
    except Exception:
        notification = f"{USER_ADDRESS}, {sender} schreibt per {channel}: {message}"

    await broadcast_notification(notification, speak=True)
    return JSONResponse({"status": "delivered", "clients": len(active_clients)})


@app.post("/webhook/clawbot/silent")
async def clawbot_webhook_silent(request: Request):
    """Wie /webhook/clawbot, aber nur Text ohne Vorlesen."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if data.get("secret") != CLAWBOT_WEBHOOK_SECRET:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    sender = data.get("sender_name", data.get("sender", "Unbekannt"))
    channel = data.get("channel", "unknown")
    message = data.get("message", "")

    notification = f"{sender} ({channel}): {message}"
    await broadcast_notification(notification, speak=False)
    return JSONResponse({"status": "delivered_silent", "clients": len(active_clients)})


# ---------------------------------------------------------------------------
# API: devices.csv hot-reload
# ---------------------------------------------------------------------------
@app.post("/api/reload-devices")
async def reload_devices():
    """devices.csv neu laden ohne Server-Neustart."""
    registry.reload()
    return JSONResponse({"status": "ok", "devices": len(registry.devices)})


# ---------------------------------------------------------------------------
# Static Files
# ---------------------------------------------------------------------------
app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/manifest.json")
async def serve_manifest():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "manifest.json"),
        media_type="application/manifest+json",
    )


@app.get("/sw.js")
async def serve_sw():
    return FileResponse(
        os.path.join(FRONTEND_DIR, "sw.js"),
        media_type="application/javascript",
    )


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    ssl_cert = os.path.join(BASE_DIR, "cert.pem")
    ssl_key = os.path.join(BASE_DIR, "key.pem")
    use_ssl = os.path.exists(ssl_cert) and os.path.exists(ssl_key)

    port = 8443
    proto = "https" if use_ssl else "http"

    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()

    print("=" * 50, flush=True)
    print("  J.A.R.V.I.S. Mobile Server", flush=True)
    print(f"  Lokal:  {proto}://localhost:{port}", flush=True)
    print(f"  Handy:  {proto}://{local_ip}:{port}", flush=True)
    if ha:
        print(f"  HA:     {HA_URL}", flush=True)
    print(f"  Webhook: {proto}://{local_ip}:{port}/webhook/clawbot", flush=True)
    if not use_ssl:
        print("", flush=True)
        print("  WARNUNG: Kein SSL! Mikrofon/Kamera/Shake", flush=True)
        print("  funktionieren nur mit HTTPS.", flush=True)
        print("  Fuehre aus: python generate_cert.py", flush=True)
    print("=" * 50, flush=True)

    kwargs = {"host": "0.0.0.0", "port": port}
    if use_ssl:
        kwargs["ssl_certfile"] = ssl_cert
        kwargs["ssl_keyfile"] = ssl_key

    uvicorn.run(app, **kwargs)
