#!/bin/bash
# ============================================================
# Jarvis Mobile — Linux CT Deployment auf Proxmox (PVE1)
# Erstellt einen Debian LXC Container und richtet Jarvis ein.
#
# Ausfuehren auf PVE1:
#   bash deploy-ct.sh
# ============================================================

set -e

# --- Konfiguration ---
CTID=7300
HOSTNAME="jarvis"
MEMORY=1024
SWAP=512
DISK_SIZE=8
CORES=2
STORAGE="local-lvm"
TEMPLATE="local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst"
BRIDGE="vmbr0"
IP="192.167.200.30/12"
GATEWAY="192.167.178.200"
NAMESERVER="192.167.178.5"
REPO_URL="https://github.com/braindeadx1/jarvis-mobile.git"

echo "=========================================="
echo "  Jarvis Mobile CT Deployment"
echo "  CTID: $CTID | IP: $IP"
echo "=========================================="

# --- Template pruefen ---
if ! pveam list local | grep -q "debian-12-standard"; then
    echo "[deploy] Template herunterladen..."
    pveam download local debian-12-standard_12.7-1_amd64.tar.zst
fi

# --- CT erstellen ---
if pct status $CTID &>/dev/null; then
    echo "[deploy] CT $CTID existiert bereits! Abbruch."
    echo "         Zum Loeschen: pct destroy $CTID --purge"
    exit 1
fi

echo "[deploy] Erstelle CT $CTID..."
pct create $CTID $TEMPLATE \
    --hostname $HOSTNAME \
    --memory $MEMORY \
    --swap $SWAP \
    --cores $CORES \
    --rootfs $STORAGE:$DISK_SIZE \
    --net0 name=eth0,bridge=$BRIDGE,ip=$IP,gw=$GATEWAY \
    --nameserver $NAMESERVER \
    --features nesting=1 \
    --onboot 1 \
    --start 0 \
    --unprivileged 1

echo "[deploy] Starte CT..."
pct start $CTID
sleep 3

# --- Software installieren ---
echo "[deploy] Installiere Software..."
pct exec $CTID -- bash -c "
    apt-get update && apt-get install -y \
        python3 python3-pip python3-venv \
        git curl openssl \
        && apt-get clean

    # Projekt klonen
    cd /opt
    git clone $REPO_URL jarvis-mobile
    cd jarvis-mobile

    # Python venv
    python3 -m venv venv
    source venv/bin/activate
    pip install --no-cache-dir -r requirements.txt
    pip install --no-cache-dir edge-tts websockets

    # SSL-Zertifikat generieren
    python3 generate_cert.py

    echo '[deploy] Installation abgeschlossen!'
"

# --- Systemd Service ---
echo "[deploy] Erstelle Systemd Service..."
pct exec $CTID -- bash -c "cat > /etc/systemd/system/jarvis.service << 'SERVICEFILE'
[Unit]
Description=Jarvis Mobile Voice Assistant
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/jarvis-mobile
ExecStart=/opt/jarvis-mobile/venv/bin/python server.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICEFILE

systemctl daemon-reload
systemctl enable jarvis.service
"

echo ""
echo "=========================================="
echo "  Deployment abgeschlossen!"
echo ""
echo "  CT: $CTID ($HOSTNAME)"
echo "  IP: ${IP%%/*}"
echo ""
echo "  Naechste Schritte:"
echo "  1. config.json auf CT anlegen:"
echo "     pct exec $CTID -- nano /opt/jarvis-mobile/config.json"
echo ""
echo "  2. Service starten:"
echo "     pct exec $CTID -- systemctl start jarvis"
echo ""
echo "  3. Logs pruefen:"
echo "     pct exec $CTID -- journalctl -u jarvis -f"
echo ""
echo "  4. Handy verbinden:"
echo "     https://${IP%%/*}:8443"
echo "=========================================="
