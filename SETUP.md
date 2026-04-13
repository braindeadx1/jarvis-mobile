# J.A.R.V.I.S. Mobile — Setup-Anleitung

Ein persoenlicher KI-Sprachassistent als PWA fuer Android mit Home Assistant Steuerung und ClawBot Integration.

**Architektur:**
```
Android (PWA) <--> FastAPI Server (Linux CT) <--> OpenRouter LLM
                         |           |
                   Home Assistant   ClawBot
                   (Smarthome)    (WhatsApp)
```

---

## Variante A: Linux CT auf Proxmox (empfohlen)

### 1. CT erstellen

Kopiere `deploy-ct.sh` auf PVE1 und fuehre es aus:
```bash
scp deploy-ct.sh root@192.167.178.6:/tmp/
ssh root@192.167.178.6
bash /tmp/deploy-ct.sh
```

Das Script erstellt CT 7300 mit:
- Debian 12, 1GB RAM, 2 Cores, 8GB Disk
- IP: 192.167.200.30
- Python 3 + alle Dependencies
- SSL-Zertifikat
- Systemd Service

### 2. Config anlegen

```bash
pct exec 7300 -- nano /opt/jarvis-mobile/config.json
```

Inhalt (siehe config.example.json fuer alle Felder).

### 3. Service starten

```bash
pct exec 7300 -- systemctl start jarvis
pct exec 7300 -- journalctl -u jarvis -f   # Logs pruefen
```

### 4. Handy verbinden

Oeffne Chrome auf Android: `https://192.167.200.30:8443`

---

## Variante B: Lokaler Windows-PC

```bash
cd G:\jarvis-mobile
pip install -r requirements.txt
pip install edge-tts
python generate_cert.py
python server.py
```

Handy: `https://DEINE_IP:8443`

---

## Bedienung

### Sprachbefehle

| Befehl | Aktion |
|--------|--------|
| "Jarvis" | Begruessung mit Wetter |
| "Mach das Licht im Wohnzimmer an" | Steuert Home Assistant |
| "Wie warm ist es im Schlafzimmer?" | Liest Temperatur aus |
| "Was laeuft zuhause?" | Haus-Ueberblick |
| "Alle Temperaturen" | Alle Raumtemperaturen |
| "Gute Nacht" / "Alles aus" | Lichter aus, Rolladen zu |
| "Suche nach ..." | Web-Suche |

### Buttons

- **Mikrofon** (Mitte) — Tap to talk
- **Kamera** (links) — Foto analysieren
- **Shake** (rechts) — Schuetteln = Mikrofon

---

## ClawBot Integration

Siehe `clawbot-skill/TOOLS_ENTRY.md` fuer die Einrichtung auf CT 7200.

---

## Devices verwalten (devices.csv)

Entitaeten in `devices.csv` hinzufuegen/entfernen.
Hot-Reload: `curl -X POST https://IP:8443/api/reload-devices -k`

| Spalte | Beschreibung |
|--------|-------------|
| entity_id | HA Entity-ID |
| friendly_name | Name fuer Jarvis |
| room | Raum |
| type | light, switch, climate, temperature, cover, door, window, security, water |
| watch | `yes` = proaktive Meldungen |

---

## Edge TTS Stimmen

| Voice | Beschreibung |
|-------|-------------|
| de-DE-ConradNeural | Maennlich, deutsch (Standard) |
| de-DE-KillianNeural | Maennlich, deutsch |
| de-DE-FlorianMultilingualNeural | Multilingual |
| en-GB-RyanNeural | Britisch-englisch |
