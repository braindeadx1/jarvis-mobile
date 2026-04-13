#!/bin/bash
# jarvis-notify — ClawBot Custom Skill
# Sendet eingehende Nachrichten an den Jarvis Mobile Webhook
#
# Aufruf durch ClawBot:
#   exec ./scripts/notify.sh "$SENDER" "$SENDER_NAME" "$CHANNEL" "$MESSAGE"
#
# Umgebungsvariablen (alternativ):
#   JARVIS_URL      — URL des Jarvis-Servers (default: http://192.167.200.XX:8443)
#   JARVIS_SECRET   — Webhook-Secret (default: jarvis-secret-2026)

SENDER="${1:-unknown}"
SENDER_NAME="${2:-Unbekannt}"
CHANNEL="${3:-whatsapp}"
MESSAGE="${4:-}"

# Jarvis Server Konfiguration
JARVIS_URL="${JARVIS_URL:-https://JARVIS_CT_IP:8443}"
JARVIS_SECRET="${JARVIS_SECRET:-jarvis-secret-2026}"

if [ -z "$MESSAGE" ]; then
    echo '{"status": "error", "message": "Keine Nachricht angegeben"}'
    exit 1
fi

# An Jarvis senden (self-signed cert akzeptieren mit -k)
RESPONSE=$(curl -s -k -X POST "${JARVIS_URL}/webhook/clawbot" \
    -H "Content-Type: application/json" \
    -d "{
        \"secret\": \"${JARVIS_SECRET}\",
        \"sender\": \"${SENDER}\",
        \"sender_name\": \"${SENDER_NAME}\",
        \"channel\": \"${CHANNEL}\",
        \"message\": $(echo "$MESSAGE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))')
    }" 2>/dev/null)

if [ $? -eq 0 ]; then
    echo "$RESPONSE"
else
    echo '{"status": "error", "message": "Jarvis Server nicht erreichbar"}'
    exit 1
fi
