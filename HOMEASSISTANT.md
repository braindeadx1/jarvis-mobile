# Home Assistant Integration

## Uebersicht

Jarvis steuert dein Smarthome ueber drei Wege:

1. **REST API** — Direkte Befehle (Licht an/aus, Temperatur setzen)
2. **WebSocket** — Live-Status-Updates (proaktive Meldungen)
3. **devices.csv** — Entitaeten-Verwaltung (erweiterbar)

## Einrichtung

### 1. Long-Lived Access Token erstellen

1. Home Assistant oeffnen → Profil (unten links)
2. Sicherheit → "Langlebige Zugriffstoken"
3. "Token erstellen" → Name: "Jarvis"
4. Token kopieren

### 2. config.json

```json
{
  "ha_url": "http://192.167.178.110:8123",
  "ha_token": "DEIN_TOKEN"
}
```

### 3. devices.csv einrichten

Die Datei definiert welche Geraete Jarvis kennt. Format:

```csv
entity_id,friendly_name,room,type,watch,notes
light.wohnzimmer,Wohnzimmer Licht,Wohnzimmer,light,no,
climate.zuhause_wohnzimmer,Heizung Wohnzimmer,Wohnzimmer,climate,yes,
sensor.temperatur_wohnzimmer,Temperatur Wohnzimmer,Wohnzimmer,temperature,yes,
```

### Geraetetypen

| Typ | Steuerung | Proaktive Meldungen |
|-----|-----------|-------------------|
| `light` | an/aus/toggle | - |
| `light_group` | an/aus (Homematic Gruppen) | - |
| `switch` | an/aus/toggle | - |
| `climate` | Temperatur setzen | Ja: zu kalt (<10°C) / zu warm (>28°C) |
| `temperature` | nur lesen | - |
| `cover` | auf/zu/Position | - |
| `door` | nur lesen | Ja: Tuer geoeffnet |
| `window` | nur lesen | - |
| `security` | nur lesen | Ja: Person erkannt, Klingel |
| `water` | nur lesen | Ja: ALARM bei Wassermelder! |

### Ueberwachung (watch=yes)

Wenn `watch` auf `yes` steht, meldet Jarvis proaktiv:
- **Tuerklingel** — "Sir, es klingelt an der Tuer"
- **Person erkannt** — "Bewegung erkannt: Vordertuer"
- **Wasser-Alarm** — "ACHTUNG! Wasser-Alarm bei ..."
- **Tuer geoeffnet** — "Die Haustuer wurde geoeffnet"
- **Temperatur-Alarm** — Bei unter 10°C oder ueber 28°C

### Neue Geraete hinzufuegen

1. Entity-ID in Home Assistant finden (Einstellungen → Geraete → Entitaet)
2. Zeile in `devices.csv` hinzufuegen
3. Hot-Reload: `curl -X POST https://IP:8443/api/reload-devices -k`

## Sprachbefehle

### Direkte Steuerung
- "Mach das Licht im Wohnzimmer an"
- "Schalte die Kueche aus"
- "Rolladen Schlafzimmer runter"
- "Heizung Wohnzimmer auf 22 Grad"
- "Markise einfahren"

### Abfragen
- "Wie warm ist es im Schlafzimmer?"
- "Was laeuft zuhause?"
- "Alle Temperaturen"
- "Status Wohnzimmer"

### Routinen
- "Gute Nacht" / "Ich gehe schlafen" / "Alles aus"
  → Alle Lichter aus, Rolladen zu, Aussensteckdosen aus

## Architektur

```
Sprache → LLM (oder lokales NLP) → HA-Befehl erkannt?
                                      |
                               Ja: parse_ha_command()
                                      |
                               execute_ha_command()
                                      |
                               HA REST API aufrufen
                                      |
                               LLM formuliert Antwort
                                      |
                               Edge TTS → Sprache
```

Parallel dazu:
```
HA WebSocket ← state_changed Events
      |
  Nur watch=yes Entitaeten
      |
  on_ha_state_change()
      |
  broadcast_notification()
      |
  Alle verbundenen Clients
```

## Homematic-spezifisch

Die meisten Geraete laufen ueber Homematic IP. Besonderheiten:
- **Lichtgruppen** sind `switch`-Entitaeten (z.B. `switch.zuhause_hauptlicht_wohnzimmer_group`)
- **Rolladen** sind `cover`-Entitaeten mit ShutterGroups
- **Thermostate** haben separate Entitaeten fuer IST-Temperatur (sensor) und SOLL (climate)
- **Wandthermostate** haben eigene Temperatur-Sensoren
