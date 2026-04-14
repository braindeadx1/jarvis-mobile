#!/usr/bin/env python3
"""
J.A.R.V.I.S. — Good Morning Clap Trigger

Laeuft auf dem Notebook, lauscht auf Doppelklatschen.
Bei Erkennung: Iron Man Style "Good Morning" Routine.

Keine externen Dependencies noetig (nur Python stdlib + pyaudio).
PyInstaller-kompatibel.
"""

import argparse
import base64
import json
import math
import os
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
import webbrowser

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
JARVIS_SERVER = "192.167.200.30"
JARVIS_PORT = 8443
JARVIS_URL = f"wss://{JARVIS_SERVER}:{JARVIS_PORT}/ws"
JARVIS_PWA_URL = f"https://{JARVIS_SERVER}:{JARVIS_PORT}/"

# Klatschen-Erkennung
SAMPLE_RATE = 44100
CHUNK = 2048
DEFAULT_THRESHOLD = 0.15
MIN_GAP = 0.1
MAX_GAP = 1.2
COOLDOWN = 10.0

# Apps
APPS = {
    "Spotify": {
        "exe": [
            os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
        ],
        "fallback_url": "https://open.spotify.com",
    },
    "Outlook": {
        "exe": [
            r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\olk.exe"),
        ],
        "fallback_url": "https://outlook.office.com",
    },
}

# SSL
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Apps oeffnen
# ---------------------------------------------------------------------------
def open_app(name, config):
    for exe_path in config.get("exe", []):
        if os.path.exists(exe_path):
            print(f"  [app] {name} starten: {os.path.basename(exe_path)}", flush=True)
            subprocess.Popen([exe_path], shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    url = config.get("fallback_url")
    if url:
        print(f"  [app] {name} im Browser", flush=True)
        webbrowser.open(url)


# ---------------------------------------------------------------------------
# Audio abspielen
# ---------------------------------------------------------------------------
def play_audio_from_base64(audio_b64):
    if not audio_b64:
        return
    audio_data = base64.b64decode(audio_b64)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_data)
        tmp_path = f.name
    try:
        if sys.platform == "win32":
            os.startfile(tmp_path)
            time.sleep(max(3, len(audio_data) / 12000))
        else:
            subprocess.run(["ffplay", "-nodisp", "-autoexit", tmp_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"  [audio] Fehler: {e}", flush=True)
    finally:
        try:
            time.sleep(1)
            os.unlink(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Jarvis Good Morning Routine
# ---------------------------------------------------------------------------
def good_morning_routine():
    print("\n" + "=" * 60, flush=True)
    print("  J.A.R.V.I.S. GOOD MORNING PROTOCOL", flush=True)
    print("=" * 60, flush=True)

    # Phase 1: Apps
    print("\n[phase 1] Systeme hochfahren...", flush=True)
    print(f"  [app] Jarvis PWA", flush=True)
    webbrowser.open(JARVIS_PWA_URL)
    time.sleep(0.5)
    for name, config in APPS.items():
        open_app(name, config)
        time.sleep(0.3)

    # Phase 2: Jarvis Begruessung
    print("\n[phase 2] Jarvis kontaktieren...", flush=True)
    try:
        import websocket
        ws = websocket.create_connection(
            JARVIS_URL, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=20)
        try:
            ws.settimeout(3)
            ws.recv()
        except Exception:
            pass

        ws.send(json.dumps({
            "type": "text",
            "text": "Jarvis, guten Morgen! Starte den Tag.",
        }))
        print("  [ws] Begruessung angefordert...", flush=True)
        ws.settimeout(30)
        try:
            while True:
                resp = ws.recv()
                data = json.loads(resp)
                if data.get("type") == "response":
                    print(f"\n  Jarvis: {data.get('text', '')}\n", flush=True)
                    audio = data.get("audio", "")
                    if audio:
                        print("  [audio] Sprachausgabe...", flush=True)
                        play_audio_from_base64(audio)
                elif data.get("type") == "status" and data.get("status") == "idle":
                    break
        except Exception:
            pass
        ws.close()
    except ImportError:
        print("  [error] websocket-client fehlt!", flush=True)
    except Exception as e:
        print(f"  [error] Jarvis nicht erreichbar: {e}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print("  Good Morning Protocol abgeschlossen.", flush=True)
    print("  Lausche wieder auf Doppelklatschen...", flush=True)
    print("=" * 60 + "\n", flush=True)


# ---------------------------------------------------------------------------
# Klatschen-Erkennung mit PyAudio
# ---------------------------------------------------------------------------
def rms_from_bytes(data, sample_width=2):
    """Berechnet RMS aus raw PCM bytes (16-bit signed)."""
    count = len(data) // sample_width
    if count == 0:
        return 0.0
    fmt = f"<{count}h"  # little-endian signed 16-bit
    samples = struct.unpack(fmt, data)
    sum_sq = sum(s * s for s in samples)
    return math.sqrt(sum_sq / count) / 32768.0  # Normiert auf 0.0-1.0


def run_clap_detection(threshold, device_index=None):
    """Klatschen-Erkennung mit PyAudio."""
    try:
        import pyaudio
    except ImportError:
        print("[error] PyAudio nicht verfuegbar. Versuche alternative Methode...", flush=True)
        run_clap_detection_waveapi(threshold)
        return

    pa = pyaudio.PyAudio()

    # Device Info
    if device_index is not None:
        dev_info = pa.get_device_info_by_index(device_index)
    else:
        dev_info = pa.get_default_input_device_info()
    print(f"[mic] Geraet: {dev_info['name']}", flush=True)

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=CHUNK,
    )

    print("[clap] Lausche auf Doppelklatschen...\n", flush=True)

    last_clap = 0.0
    last_trigger = 0.0

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            now = time.time()

            if now - last_trigger < COOLDOWN:
                continue

            rms = rms_from_bytes(data)

            if rms > threshold:
                gap = now - last_clap
                if gap >= MIN_GAP:
                    if gap <= MAX_GAP and last_clap > 0:
                        print(f"\n[clap] Doppelklatschen! (rms={rms:.3f})", flush=True)
                        last_clap = 0.0
                        last_trigger = now
                        t = threading.Thread(target=good_morning_routine, daemon=True)
                        t.start()
                    else:
                        last_clap = now
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


# ---------------------------------------------------------------------------
# Fallback: Windows WASAPI via ctypes (kein PyAudio noetig)
# ---------------------------------------------------------------------------
def run_clap_detection_waveapi(threshold):
    """Fallback Klatschen-Erkennung mit Windows waveIn API."""
    import ctypes
    import ctypes.wintypes as wt

    winmm = ctypes.windll.winmm

    WAVE_FORMAT_PCM = 1
    CALLBACK_NULL = 0
    WHDR_DONE = 1

    class WAVEFORMATEX(ctypes.Structure):
        _fields_ = [
            ("wFormatTag", wt.WORD),
            ("nChannels", wt.WORD),
            ("nSamplesPerSec", wt.DWORD),
            ("nAvgBytesPerSec", wt.DWORD),
            ("nBlockAlign", wt.WORD),
            ("wBitsPerSample", wt.WORD),
            ("cbSize", wt.WORD),
        ]

    class WAVEHDR(ctypes.Structure):
        _fields_ = [
            ("lpData", ctypes.POINTER(ctypes.c_char)),
            ("dwBufferLength", wt.DWORD),
            ("dwBytesRecorded", wt.DWORD),
            ("dwUser", ctypes.POINTER(wt.DWORD)),
            ("dwFlags", wt.DWORD),
            ("dwLoops", wt.DWORD),
            ("lpNext", ctypes.c_void_p),
            ("reserved", ctypes.POINTER(wt.DWORD)),
        ]

    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_PCM
    fmt.nChannels = 1
    fmt.nSamplesPerSec = SAMPLE_RATE
    fmt.wBitsPerSample = 16
    fmt.nBlockAlign = fmt.nChannels * fmt.wBitsPerSample // 8
    fmt.nAvgBytesPerSec = fmt.nSamplesPerSec * fmt.nBlockAlign
    fmt.cbSize = 0

    # Verfuegbare Geraete auflisten
    num_devs = winmm.waveInGetNumDevs()
    print(f"[mic] {num_devs} Aufnahmegeraet(e) gefunden", flush=True)
    if num_devs == 0:
        print("[error] Kein Mikrofon gefunden! Bitte Mikrofon anschliessen oder aktivieren.", flush=True)
        return

    class WAVEINCAPS(ctypes.Structure):
        _fields_ = [
            ("wMid", wt.WORD),
            ("wPid", wt.WORD),
            ("vDriverVersion", wt.UINT),
            ("szPname", ctypes.c_wchar * 32),
            ("dwFormats", wt.DWORD),
            ("wChannels", wt.WORD),
            ("wReserved1", wt.WORD),
        ]

    for i in range(num_devs):
        caps = WAVEINCAPS()
        winmm.waveInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(WAVEINCAPS))
        print(f"  [{i}] {caps.szPname} ({caps.wChannels}ch)", flush=True)

    # Erstes Geraet verwenden
    dev_id = 0
    hwi = wt.HANDLE()
    # Verschiedene Sample-Raten probieren
    for rate in [44100, 48000, 16000, 22050, 8000]:
        fmt.nSamplesPerSec = rate
        fmt.nAvgBytesPerSec = rate * fmt.nBlockAlign
        result = winmm.waveInOpen(ctypes.byref(hwi), dev_id,
                                   ctypes.byref(fmt), 0, 0, CALLBACK_NULL)
        if result == 0:
            print(f"[mic] Sample-Rate: {rate} Hz", flush=True)
            break
        print(f"  [mic] {rate} Hz nicht unterstuetzt (err={result})", flush=True)
    else:
        print("[error] Kein kompatibles Audio-Format gefunden!", flush=True)
        return

    # Double-Buffering
    NUM_BUFS = 4
    buf_size = CHUNK * fmt.nBlockAlign
    bufs = []
    hdrs = []
    for i in range(NUM_BUFS):
        b = ctypes.create_string_buffer(buf_size)
        h = WAVEHDR()
        h.lpData = ctypes.cast(b, ctypes.POINTER(ctypes.c_char))
        h.dwBufferLength = buf_size
        h.dwFlags = 0
        h.dwBytesRecorded = 0
        r1 = winmm.waveInPrepareHeader(hwi, ctypes.byref(h), ctypes.sizeof(WAVEHDR))
        r2 = winmm.waveInAddBuffer(hwi, ctypes.byref(h), ctypes.sizeof(WAVEHDR))
        if r1 != 0 or r2 != 0:
            print(f"[error] Buffer {i} prep={r1} add={r2}", flush=True)
        bufs.append(b)
        hdrs.append(h)

    r = winmm.waveInStart(hwi)
    print(f"[mic] waveInStart: {'OK' if r == 0 else f'ERROR {r}'}", flush=True)
    print("[clap] Lausche auf Doppelklatschen...\n", flush=True)

    last_clap = 0.0
    last_trigger = 0.0
    max_rms = 0.0
    last_debug = 0.0

    try:
        while True:
            got_data = False
            for i in range(NUM_BUFS):
                if hdrs[i].dwFlags & WHDR_DONE:
                    got_data = True
                    recorded = hdrs[i].dwBytesRecorded
                    if recorded > 0:
                        data = bufs[i].raw[:recorded]
                        now = time.time()

                        if now - last_trigger >= COOLDOWN:
                            rms = rms_from_bytes(data)
                            max_rms = max(max_rms, rms)

                            # Debug-Pegel
                            if now - last_debug > 0.3:
                                bar = "#" * min(40, int(max_rms * 200))
                                thr_mark = "T" if max_rms > threshold else " "
                                print(f"\r  [{thr_mark}] rms={max_rms:.4f} |{bar:<40}|", end="", flush=True)
                                max_rms = 0.0
                                last_debug = now

                            if rms > threshold:
                                gap = now - last_clap
                                if gap >= MIN_GAP:
                                    if gap <= MAX_GAP and last_clap > 0:
                                        print(f"\n[clap] Doppelklatschen! (rms={rms:.3f})", flush=True)
                                        last_clap = 0.0
                                        last_trigger = now
                                        t = threading.Thread(target=good_morning_routine, daemon=True)
                                        t.start()
                                    else:
                                        print(f"\n[clap] Erstes Klatschen (rms={rms:.3f})", flush=True)
                                        last_clap = now

                    # Buffer zurueck in die Queue
                    hdrs[i].dwFlags = 0
                    hdrs[i].dwBytesRecorded = 0
                    winmm.waveInAddBuffer(hwi, ctypes.byref(hdrs[i]), ctypes.sizeof(WAVEHDR))

            if not got_data:
                time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        winmm.waveInStop(hwi)
        for i in range(NUM_BUFS):
            winmm.waveInUnprepareHeader(hwi, ctypes.byref(hdrs[i]), ctypes.sizeof(WAVEHDR))
        winmm.waveInClose(hwi)


# ---------------------------------------------------------------------------
# Device listing
# ---------------------------------------------------------------------------
def list_devices():
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        print("Audio-Geraete:")
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                default = " (DEFAULT)" if i == pa.get_default_input_device_info()["index"] else ""
                print(f"  [{i}] {info['name']}{default}")
        pa.terminate()
    except ImportError:
        print("PyAudio nicht installiert — nutze Windows WaveAPI (Default-Mikrofon)")


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jarvis Good Morning Clap Trigger")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"RMS-Schwellwert (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--list-devices", action="store_true",
                        help="Audio-Geraete auflisten")
    parser.add_argument("--device", type=int, default=None,
                        help="Audio-Device Index")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        sys.exit(0)

    print("=" * 60, flush=True)
    print("  J.A.R.V.I.S. Good Morning Clap Trigger", flush=True)
    print(f"  Server:      {JARVIS_URL}", flush=True)
    print(f"  Schwellwert: {args.threshold}", flush=True)
    print(f"  Apps:        Spotify, Outlook, Jarvis PWA", flush=True)
    print("  Doppelklatschen = Good Morning Routine", flush=True)
    print("  Ctrl+C zum Beenden", flush=True)
    print("=" * 60, flush=True)

    try:
        run_clap_detection(args.threshold, args.device)
    except KeyboardInterrupt:
        pass
    print("\n[jarvis] Beendet.", flush=True)
