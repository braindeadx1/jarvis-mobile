/**
 * Jarvis Mobile — PWA Frontend
 * Shake-Trigger, Spracherkennung, Kamera, WebSocket
 */

// ===== State =====
let ws = null;
let isListening = false;
let shakeEnabled = false;
let recognition = null;
let audioQueue = [];
let isPlayingAudio = false;

// ===== DOM =====
const reactor = document.getElementById("reactor");
const statusText = document.getElementById("status-text");
const responseText = document.getElementById("response-text");
const connectionDot = document.getElementById("connection-dot");
const connectionText = document.getElementById("connection-text");
const btnTalk = document.getElementById("btn-talk");
const btnCamera = document.getElementById("btn-camera");
const btnShake = document.getElementById("btn-shake");
const cameraOverlay = document.getElementById("camera-overlay");
const cameraPreview = document.getElementById("camera-preview");
const btnCapture = document.getElementById("btn-capture");
const btnCameraClose = document.getElementById("btn-camera-close");

// ===== WebSocket =====
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/ws`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    connectionDot.classList.add("connected");
    connectionText.textContent = "Verbunden";
    setStatus("idle", "Bereit");
  };

  ws.onclose = () => {
    connectionDot.classList.remove("connected");
    connectionText.textContent = "Getrennt";
    setStatus("idle", "Keine Verbindung");
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => {
    ws.close();
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
  };
}

function handleMessage(data) {
  if (data.type === "status") {
    const labels = {
      thinking: "Denkt nach...",
      speaking: "Spricht...",
      searching: "Sucht...",
      idle: "Bereit",
    };
    setStatus(data.status, labels[data.status] || data.status);
  }

  if (data.type === "response") {
    showResponse(data.text);
    if (data.audio) {
      queueAudio(data.audio);
    }
  }

  // Proaktive Benachrichtigungen (HA, ClawBot)
  if (data.type === "notification") {
    showNotification(data.text);
    if (data.audio) {
      queueAudio(data.audio);
    }
    // Vibration bei Benachrichtigung
    if (navigator.vibrate) {
      navigator.vibrate([100, 50, 100]);
    }
  }
}

// ===== UI Updates =====
function setStatus(state, label) {
  reactor.className = state;
  statusText.textContent = label;
}

function showResponse(text) {
  responseText.textContent = text;
  responseText.classList.remove("notification");
  responseText.classList.add("visible");
}

function showNotification(text) {
  responseText.textContent = text;
  responseText.classList.add("visible", "notification");
  // Nach 10s Notification-Style entfernen
  setTimeout(() => responseText.classList.remove("notification"), 10000);
}

// ===== Audio Playback =====
function queueAudio(base64Audio) {
  audioQueue.push(base64Audio);
  if (!isPlayingAudio) {
    playNextAudio();
  }
}

function playNextAudio() {
  if (audioQueue.length === 0) {
    isPlayingAudio = false;
    setStatus("idle", "Bereit");
    return;
  }

  isPlayingAudio = true;
  setStatus("speaking", "Spricht...");

  const audioData = audioQueue.shift();
  const audioBytes = atob(audioData);
  const arrayBuffer = new ArrayBuffer(audioBytes.length);
  const view = new Uint8Array(arrayBuffer);
  for (let i = 0; i < audioBytes.length; i++) {
    view[i] = audioBytes.charCodeAt(i);
  }

  const blob = new Blob([arrayBuffer], { type: "audio/mpeg" });
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);

  audio.onended = () => {
    URL.revokeObjectURL(url);
    playNextAudio();
  };

  audio.onerror = () => {
    URL.revokeObjectURL(url);
    playNextAudio();
  };

  audio.play().catch(() => playNextAudio());
}

// ===== Speech Recognition (Web Speech API) =====
function initSpeechRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    console.warn("Web Speech API nicht verfuegbar");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "de-DE";
  recognition.interimResults = false;
  recognition.continuous = false;

  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    console.log("Erkannt:", text);
    sendText(text);
  };

  recognition.onend = () => {
    isListening = false;
    btnTalk.classList.remove("recording");
    if (reactor.className === "listening") {
      setStatus("idle", "Bereit");
    }
  };

  recognition.onerror = (event) => {
    console.warn("Speech error:", event.error);
    isListening = false;
    btnTalk.classList.remove("recording");
    setStatus("idle", "Bereit");
  };
}

function startListening() {
  if (!recognition) {
    initSpeechRecognition();
  }
  if (!recognition) {
    showResponse("Spracherkennung nicht verfuegbar. Nutze Chrome auf Android.");
    return;
  }
  if (isListening) return;

  isListening = true;
  btnTalk.classList.add("recording");
  setStatus("listening", "Hoert zu...");
  responseText.classList.remove("visible");

  try {
    recognition.start();
  } catch (e) {
    // Already started
    isListening = false;
    btnTalk.classList.remove("recording");
  }
}

function stopListening() {
  if (recognition && isListening) {
    recognition.stop();
  }
}

function sendText(text) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "text", text }));
    setStatus("thinking", "Denkt nach...");
  }
}

// ===== Camera =====
let cameraStream = null;

async function openCamera() {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    cameraPreview.srcObject = cameraStream;
    cameraOverlay.classList.remove("hidden");
  } catch (e) {
    console.error("Kamera-Fehler:", e);
    showResponse("Kamera-Zugriff verweigert. Erlaube den Zugriff in den Browser-Einstellungen.");
  }
}

function closeCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach((t) => t.stop());
    cameraStream = null;
  }
  cameraPreview.srcObject = null;
  cameraOverlay.classList.add("hidden");
}

function captureAndSend() {
  const canvas = document.createElement("canvas");
  canvas.width = cameraPreview.videoWidth;
  canvas.height = cameraPreview.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(cameraPreview, 0, 0);

  // JPEG komprimieren
  const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
  const base64 = dataUrl.split(",")[1];

  closeCamera();

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "image", image: base64, text: "" }));
    setStatus("thinking", "Analysiert Bild...");
    showResponse("Bild wird analysiert...");
  }
}

// ===== Shake Detection =====
let lastShake = 0;
const SHAKE_THRESHOLD = 25;
const SHAKE_COOLDOWN = 2000;

function enableShake() {
  // iOS 13+ braucht Permission
  if (typeof DeviceMotionEvent !== "undefined" && typeof DeviceMotionEvent.requestPermission === "function") {
    DeviceMotionEvent.requestPermission()
      .then((state) => {
        if (state === "granted") {
          window.addEventListener("devicemotion", handleShake);
          shakeEnabled = true;
          btnShake.classList.add("active");
        }
      })
      .catch(console.error);
  } else if (typeof DeviceMotionEvent !== "undefined") {
    window.addEventListener("devicemotion", handleShake);
    shakeEnabled = true;
    btnShake.classList.add("active");
  }
}

function disableShake() {
  window.removeEventListener("devicemotion", handleShake);
  shakeEnabled = false;
  btnShake.classList.remove("active");
}

function handleShake(event) {
  const acc = event.accelerationIncludingGravity;
  if (!acc) return;

  const force = Math.sqrt(acc.x ** 2 + acc.y ** 2 + acc.z ** 2);

  if (force > SHAKE_THRESHOLD) {
    const now = Date.now();
    if (now - lastShake > SHAKE_COOLDOWN) {
      lastShake = now;
      onShakeDetected();
    }
  }
}

function onShakeDetected() {
  // Haptic Feedback
  if (navigator.vibrate) {
    navigator.vibrate(100);
  }
  startListening();
}

// ===== Event Listeners =====

// Talk Button: Tap to start, tap again to stop
btnTalk.addEventListener("click", () => {
  if (isListening) {
    stopListening();
  } else {
    startListening();
  }
});

// Camera Button
btnCamera.addEventListener("click", openCamera);
btnCapture.addEventListener("click", captureAndSend);
btnCameraClose.addEventListener("click", closeCamera);

// Shake Toggle
btnShake.addEventListener("click", () => {
  if (shakeEnabled) {
    disableShake();
  } else {
    enableShake();
  }
});

// ===== PWA Service Worker =====
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// ===== Init =====
initSpeechRecognition();
connectWS();

// Beim ersten Tap Audio-Kontext aktivieren (Autoplay-Policy)
document.addEventListener(
  "click",
  () => {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    ctx.resume().then(() => ctx.close());
  },
  { once: true }
);
