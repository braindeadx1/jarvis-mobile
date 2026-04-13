#!/usr/bin/env python3
"""
Jarvis — Double Clap Trigger (Remote)
Laeuft auf dem Notebook, lauscht auf Doppelklatschen.
Bei Erkennung: verbindet sich per WebSocket mit dem Jarvis-Server
und sendet "Jarvis activate".

Voraussetzungen:
    pip install sounddevice numpy websocket-client

Nutzung:
    python clap-trigger.py                          # Standard: wss://192.168.1.100:8443
    python clap-trigger.py 192.168.1.100            # Eigene IP
    python clap-trigger.py 192.168.1.100 8443       # Eigene IP + Port
"""

import json
import ssl
import sys
import time

import numpy as np
import sounddevice as sd

# ---------------------------------------------------------------------------
# Server-Verbindung
# ---------------------------------------------------------------------------
DEFAULT_HOST = "192.167.178.169"  # IP des Jarvis-Servers (Windows-PC)
DEFAULT_PORT = 8443

host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
SERVER_URL = f"wss://{host}:{port}/ws"

# ---------------------------------------------------------------------------
# Klatschen-Erkennung
# ---------------------------------------------------------------------------
SAMPLE_RATE = 44100
BLOCK_SIZE = 1024
THRESHOLD = 0.15       # RMS-Schwellwert — niedriger = empfindlicher
MIN_GAP = 0.1          # Mindestabstand zwischen Klatschern (Sekunden)
MAX_GAP = 1.2          # Maximalabstand zwischen Klatschern
COOLDOWN = 3.0         # Pause nach Trigger

last_clap_time = 0.0
last_trigger_time = 0.0


def send_activation():
    """Sendet 'Jarvis activate' an den Server via WebSocket."""
    try:
        import websocket
        # Selbstsigniertes Zertifikat akzeptieren
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        print(f"[jarvis] Verbinde mit {SERVER_URL}...", flush=True)
        ws = websocket.create_connection(SERVER_URL, sslopt={"cert_reqs": ssl.CERT_NONE})

        # Config-Nachricht vom Server lesen (falls vorhanden)
        try:
            ws.settimeout(2)
            ws.recv()
        except Exception:
            pass

        ws.send(json.dumps({"type": "text", "text": "Jarvis activate"}))
        print("[jarvis] 'Jarvis activate' gesendet!", flush=True)

        # Auf Antwort warten und anzeigen
        ws.settimeout(15)
        try:
            while True:
                resp = ws.recv()
                data = json.loads(resp)
                if data.get("type") == "response":
                    print(f"[jarvis] Jarvis: {data.get('text', '')}", flush=True)
                elif data.get("type") == "status" and data.get("status") == "idle":
                    break
        except Exception:
            pass

        ws.close()
        print("[jarvis] Verbindung geschlossen.", flush=True)

    except ImportError:
        print("[jarvis] FEHLER: websocket-client nicht installiert!", flush=True)
        print("         pip install websocket-client", flush=True)
    except Exception as e:
        print(f"[jarvis] Verbindungsfehler: {e}", flush=True)


def audio_callback(indata, frames, time_info, status):
    global last_clap_time, last_trigger_time

    now = time.time()

    # Cooldown nach letztem Trigger
    if now - last_trigger_time < COOLDOWN:
        return

    rms = float(np.sqrt(np.mean(indata ** 2)))

    if rms > THRESHOLD:
        gap = now - last_clap_time

        if gap >= MIN_GAP:
            if gap <= MAX_GAP and last_clap_time > 0:
                # Zweites Klatschen — Trigger!
                print(f"\n[jarvis] Doppelklatschen erkannt!", flush=True)
                last_clap_time = 0.0
                last_trigger_time = now
                send_activation()
                print(f"\n[jarvis] Lausche wieder...", flush=True)
            else:
                # Erstes Klatschen
                print(f"[jarvis] Erstes Klatschen (rms={rms:.3f})", flush=True)
                last_clap_time = now


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 50, flush=True)
    print("  J.A.R.V.I.S. Clap Trigger (Remote)", flush=True)
    print(f"  Server: {SERVER_URL}", flush=True)
    print(f"  Schwellwert: {THRESHOLD}", flush=True)
    print("  Doppelklatschen = Jarvis aktivieren", flush=True)
    print("  Ctrl+C zum Beenden", flush=True)
    print("=" * 50, flush=True)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        ):
            print("[jarvis] Lausche auf Doppelklatschen...\n", flush=True)
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n[jarvis] Beendet.", flush=True)
    except Exception as e:
        print(f"[jarvis] Fehler: {e}", flush=True)
        if "PortAudio" in str(e) or "sounddevice" in str(e):
            print("         Stelle sicher dass ein Mikrofon angeschlossen ist.", flush=True)
