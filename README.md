# J.A.R.V.I.S. Mobile

Persoenlicher KI-Sprachassistent als Android PWA mit Home Assistant Steuerung.

## Features

- **Sprachsteuerung** — Web Speech API + Edge TTS (kostenlos)
- **Shake-Trigger** — Handy schuetteln aktiviert Jarvis
- **Kamera-Analyse** — Foto aufnehmen, KI beschreibt es
- **Home Assistant** — Licht, Heizung, Rolladen, Sensoren steuern
- **Proaktive Meldungen** — Tuerklingel, Wasser-Alarm, Temperaturen
- **ClawBot Integration** — WhatsApp-Nachrichten vorlesen
- **Web-Suche** — Recherche mit Zusammenfassung
- **Jarvis-Persoenlichkeit** — Trockener britischer Butler-Humor

## Tech Stack

| Komponente | Technologie |
|-----------|-------------|
| Frontend | PWA (HTML/JS/CSS) |
| Backend | FastAPI (Python) |
| LLM | OpenRouter (GPT-4o-mini, Claude, etc.) |
| TTS | Edge TTS (kostenlos) / ElevenLabs |
| STT | Web Speech API (Chrome) |
| Smarthome | Home Assistant REST + WebSocket |
| Messaging | ClawBot Webhook |

## Setup

Siehe [SETUP.md](SETUP.md) fuer die vollstaendige Anleitung.

## Lizenz

MIT
