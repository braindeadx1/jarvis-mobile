# Eintrag fuer ClawBot TOOLS.md

Fuege folgenden Block in `/root/clawd/TOOLS.md` auf CT 7200 ein:

```markdown
## jarvis-notify
**Trigger:** eingehende Nachricht weiterleiten, Jarvis benachrichtigen, Nachricht vorlesen
**Beschreibung:** Leitet eingehende Nachrichten an den Jarvis Mobile Assistenten weiter, damit er sie vorliest.
**Aufruf:**
\`\`\`bash
exec /root/clawd/skills/jarvis-notify/scripts/notify.sh "$SENDER" "$SENDER_NAME" "$CHANNEL" "$MESSAGE"
\`\`\`
**Hinweis:** Der Jarvis-Server muss laufen. Wird automatisch bei eingehenden WhatsApp-Nachrichten getriggert.
```
