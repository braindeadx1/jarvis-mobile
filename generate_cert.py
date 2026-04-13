"""
Generiert ein selbstsigniertes SSL-Zertifikat fuer den Jarvis Mobile Server.
Android Chrome braucht HTTPS fuer Mikrofon, Kamera und Shake-Erkennung.
"""
import subprocess
import os
import sys

CERT_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(CERT_DIR, "key.pem")
CERT_FILE = os.path.join(CERT_DIR, "cert.pem")


def generate():
    if os.path.exists(KEY_FILE) and os.path.exists(CERT_FILE):
        print("[cert] Zertifikate existieren bereits. Loesche sie, um neue zu generieren.")
        return

    # Versuche openssl (Git for Windows bringt es mit)
    openssl_paths = [
        "openssl",
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
    ]

    openssl = None
    for path in openssl_paths:
        try:
            subprocess.run([path, "version"], capture_output=True, check=True)
            openssl = path
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    if not openssl:
        print("[cert] FEHLER: openssl nicht gefunden.")
        print("       Installiere Git for Windows (https://git-scm.com) oder OpenSSL.")
        sys.exit(1)

    # Lokale IP ermitteln
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    finally:
        s.close()

    print(f"[cert] Lokale IP: {local_ip}")
    print(f"[cert] Generiere selbstsigniertes Zertifikat...")

    # Zertifikat mit SAN (Subject Alternative Name) fuer IP-Zugriff
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", KEY_FILE,
        "-out", CERT_FILE,
        "-days", "365",
        "-nodes",
        "-subj", f"/CN=Jarvis Mobile/O=Jarvis/C=DE",
        "-addext", f"subjectAltName=IP:{local_ip},IP:127.0.0.1,DNS:localhost",
    ], check=True)

    print(f"[cert] Fertig!")
    print(f"       Key:  {KEY_FILE}")
    print(f"       Cert: {CERT_FILE}")
    print(f"")
    print(f"  Oeffne auf dem Handy: https://{local_ip}:8443")
    print(f"  Akzeptiere die Sicherheitswarnung beim ersten Besuch.")


if __name__ == "__main__":
    generate()
