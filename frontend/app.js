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
const btnStop = document.getElementById("btn-stop");
const btnShake = document.getElementById("btn-shake");
const cameraOverlay = document.getElementById("camera-overlay");
const cameraPreview = document.getElementById("camera-preview");
const btnCapture = document.getElementById("btn-capture");
const btnCameraClose = document.getElementById("btn-camera-close");
const hudLines = document.getElementById("hud-lines");

// ===== WebSocket =====
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${location.host}/ws`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    connectionDot.classList.add("connected");
    connectionText.textContent = "Verbunden";
    setStatus("idle", "SYSTEMS ONLINE");
  };

  ws.onclose = () => {
    connectionDot.classList.remove("connected");
    connectionText.textContent = "Getrennt";
    setStatus("idle", "CONNECTION LOST");
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
  // Config mit Modell-Liste vom Server
  if (data.type === "config") {
    if (data.models) {
      buildModelSelector(data.models, data.current_model);
    }
  }

  // Modell-Wechsel bestaetigt
  if (data.type === "model_changed") {
    const sel = document.getElementById("model-select");
    if (sel) sel.value = data.model;
    showResponse(`Modell gewechselt: ${data.name}`);
  }

  if (data.type === "status") {
    const labels = {
      thinking: "ANALYZING",
      speaking: "TRANSMITTING",
      searching: "SCANNING",
      idle: "SYSTEMS ONLINE",
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

  if (data.type === "telemetry") {
    renderHudLines(data.lines || []);
  }
}

// ===== HUD Terminal =====
const HUD_MAX_LINES = 7;

function renderHudLines(lines) {
  if (!hudLines) return;
  hudLines.innerHTML = "";
  const display = lines.slice(0, HUD_MAX_LINES);
  display.forEach((text, i) => {
    const div = document.createElement("div");
    div.className = "hud-line" + (isDataLine(text) ? " data" : "");
    div.textContent = "> " + text;
    div.style.animationDelay = `${i * 80}ms`;
    hudLines.appendChild(div);
  });
}

function isDataLine(text) {
  return /[\d%]|NODE|VM|CT|RUNNING|LEISTUNG|WALLBOX|BATTERIE|UPTIME|LADE/.test(text);
}

// ===== UI Updates =====
let idleLifeInterval = null;

function setStatus(state, label) {
  reactor.className = state;
  statusText.textContent = label;

  // Manage idle life animations
  if (state === "idle") {
    startIdleLife();
  } else {
    stopIdleLife();
  }
}

function startIdleLife() {
  stopIdleLife();
  // Periodic subtle effects while idle
  idleLifeInterval = setInterval(() => {
    if (reactor.className !== "idle") return;
    // Random flicker effect
    reactor.classList.add("idle-flicker");
    setTimeout(() => reactor.classList.remove("idle-flicker"), 500);
  }, 6000 + Math.random() * 8000);
}

function stopIdleLife() {
  if (idleLifeInterval) {
    clearInterval(idleLifeInterval);
    idleLifeInterval = null;
  }
  reactor.classList.remove("idle-flicker");
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

// ===== Audio Playback + Visualization =====
let vizCtx = null;
let vizAnalyser = null;
let vizAnimId = null;

function getVizContext() {
  if (!vizCtx) {
    vizCtx = new (window.AudioContext || window.webkitAudioContext)();
    vizAnalyser = vizCtx.createAnalyser();
    vizAnalyser.fftSize = 256;
    vizAnalyser.smoothingTimeConstant = 0.65;
    vizAnalyser.connect(vizCtx.destination);
  }
  if (vizCtx.state === "suspended") vizCtx.resume();
  return vizAnalyser;
}

function startViz() {
  const core = document.querySelector(".reactor-core");
  const coreInner = document.querySelector(".core-inner");
  const energyPulse = document.querySelector(".energy-pulse");
  reactor.classList.add("audio-reactive");

  const analyser = getVizContext();
  const dataArray = new Uint8Array(analyser.frequencyBinCount);

  function tick() {
    analyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
    const level = sum / dataArray.length / 255; // 0.0 – 1.0

    if (core) {
      const scale = 1 + level * 0.45;
      const glow = 25 + level * 55;
      const alpha = 0.45 + level * 0.55;
      core.style.transform = `translate(-50%,-50%) scale(${scale})`;
      core.style.boxShadow =
        `0 0 ${glow}px hsla(210,100%,55%,${alpha}),` +
        `0 0 ${glow * 2.5}px hsla(210,100%,50%,${alpha * 0.35})`;
    }
    if (coreInner) {
      coreInner.style.transform = `translate(-50%,-50%) scale(${0.9 + level * 0.35})`;
    }
    if (energyPulse) {
      energyPulse.style.animationDuration = `${1.8 - level * 1.2}s`;
    }

    vizAnimId = requestAnimationFrame(tick);
  }
  tick();
}

function stopViz() {
  if (vizAnimId) {
    cancelAnimationFrame(vizAnimId);
    vizAnimId = null;
  }
  reactor.classList.remove("audio-reactive");
  const core = document.querySelector(".reactor-core");
  const coreInner = document.querySelector(".core-inner");
  const energyPulse = document.querySelector(".energy-pulse");
  if (core) { core.style.transform = ""; core.style.boxShadow = ""; }
  if (coreInner) { coreInner.style.transform = ""; }
  if (energyPulse) { energyPulse.style.animationDuration = ""; }
}

function queueAudio(base64Audio) {
  audioQueue.push(base64Audio);
  if (!isPlayingAudio) {
    playNextAudio();
  }
}

function playNextAudio() {
  if (audioQueue.length === 0) {
    isPlayingAudio = false;
    stopViz();
    setStatus("idle", "SYSTEMS ONLINE");
    return;
  }

  isPlayingAudio = true;
  setStatus("speaking", "TRANSMITTING");

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

  // Connect to Web Audio analyser for visualization
  try {
    const analyser = getVizContext();
    const source = vizCtx.createMediaElementSource(audio);
    source.connect(analyser);
    startViz();
  } catch (e) {
    console.warn("Audio visualization unavailable:", e);
  }

  audio.onended = () => {
    URL.revokeObjectURL(url);
    playNextAudio();
  };

  audio.onerror = () => {
    URL.revokeObjectURL(url);
    stopViz();
    playNextAudio();
  };

  audio.play().catch(() => { stopViz(); playNextAudio(); });
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
      setStatus("idle", "SYSTEMS ONLINE");
    }
  };

  recognition.onerror = (event) => {
    console.warn("Speech error:", event.error);
    isListening = false;
    btnTalk.classList.remove("recording");
    setStatus("idle", "SYSTEMS ONLINE");
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
  setStatus("listening", "LISTENING");
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
    setStatus("thinking", "ANALYZING");
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
    setStatus("thinking", "VISUAL ANALYSIS");
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

// ===== Clap Detection (Web Audio API) =====
let clapEnabled = false;
let clapAudioCtx = null;
let clapAnalyser = null;
let clapStream = null;
let lastClapTime = 0;
let lastClapTrigger = 0;
const CLAP_THRESHOLD = 0.25;      // RMS threshold — nur laute Impulse
const CLAP_SILENCE = 0.05;        // Muss zwischen Klatschern leise werden
const CLAP_MIN_GAP = 150;         // ms zwischen Klatschern
const CLAP_MAX_GAP = 800;         // ms max Abstand (enger = weniger Fehlausloesung)
const CLAP_COOLDOWN = 10000;      // ms nach Trigger

async function enableClap() {
  try {
    clapStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    clapAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = clapAudioCtx.createMediaStreamSource(clapStream);
    const processor = clapAudioCtx.createScriptProcessor(2048, 1, 1);

    processor.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      const rms = Math.sqrt(sum / data.length);

      // Debug: Pegel im Status anzeigen
      const now = Date.now();
      if (!enableClap._lastDebug) enableClap._lastDebug = 0;
      if (!enableClap._maxRms) enableClap._maxRms = 0;
      enableClap._maxRms = Math.max(enableClap._maxRms, rms);
      if (now - enableClap._lastDebug > 300) {
        const bar = "█".repeat(Math.min(20, Math.round(enableClap._maxRms * 100)));
        const thr = rms > CLAP_THRESHOLD ? " !" : "";
        statusText.textContent = `🎤 ${enableClap._maxRms.toFixed(3)} ${bar}${thr}`;
        enableClap._maxRms = 0;
        enableClap._lastDebug = now;
      }

      if (now - lastClapTrigger < CLAP_COOLDOWN) return;

      // Zwischen zwei Klatschern muss es leise geworden sein
      if (!enableClap._wasQuiet) enableClap._wasQuiet = true;
      if (rms < CLAP_SILENCE) enableClap._wasQuiet = true;

      if (rms > CLAP_THRESHOLD && enableClap._wasQuiet) {
        enableClap._wasQuiet = false;  // Warten bis wieder leise
        const gap = now - lastClapTime;
        if (gap >= CLAP_MIN_GAP) {
          if (gap <= CLAP_MAX_GAP && lastClapTime > 0) {
            // Doppelklatschen!
            lastClapTime = 0;
            lastClapTrigger = now;
            onClapDetected();
          } else {
            lastClapTime = now;
            statusText.textContent = "👏 Erstes Klatschen...";
          }
        }
      }
    };

    source.connect(processor);
    processor.connect(clapAudioCtx.destination);
    clapEnabled = true;

    const btnClap = document.getElementById("btn-clap");
    if (btnClap) btnClap.classList.add("active");
    console.log("[clap] Klatschen-Erkennung aktiv");
  } catch (err) {
    console.error("[clap] Mikrofon-Fehler:", err);
    alert("Mikrofon-Zugriff verweigert. Bitte Berechtigung erteilen.");
  }
}

function disableClap() {
  if (clapStream) {
    clapStream.getTracks().forEach((t) => t.stop());
    clapStream = null;
  }
  if (clapAudioCtx) {
    clapAudioCtx.close();
    clapAudioCtx = null;
  }
  clapEnabled = false;
  const btnClap = document.getElementById("btn-clap");
  if (btnClap) btnClap.classList.remove("active");
}

function openProtocol(url) {
  const a = document.createElement("a");
  a.href = url;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => a.remove(), 100);
}

function onClapDetected() {
  console.log("[clap] Doppelklatschen erkannt!");
  statusText.textContent = "🚀 Good Morning Protocol...";

  // Phase 1: Apps oeffnen (mit Verzoegerung damit Browser nicht blockiert)
  setTimeout(() => openProtocol("spotify:"), 200);
  setTimeout(() => openProtocol("ms-outlook:"), 600);

  // Phase 2: Jarvis begruessen
  setTimeout(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({
        type: "text",
        text: "Jarvis, guten Morgen! Starte den Tag."
      }));
      setStatus("thinking", "INITIALIZING");
    }
  }, 1000);
}

// ===== Model Selector =====
function buildModelSelector(models, currentModel) {
  const container = document.getElementById("model-container");
  if (!container) return;

  // Bestehenden Selector entfernen falls vorhanden
  container.innerHTML = "";

  const select = document.createElement("select");
  select.id = "model-select";

  const tierLabels = { budget: "💰 Budget", mid: "⚡ Mittelklasse", premium: "🔥 Premium" };
  let currentTier = "";

  for (const m of models) {
    if (m.tier !== currentTier) {
      currentTier = m.tier;
      const optgroup = document.createElement("optgroup");
      optgroup.label = tierLabels[m.tier] || m.tier;
      select.appendChild(optgroup);
    }

    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.name}  ·  $${m.input} / $${m.output}`;
    if (m.id === currentModel) opt.selected = true;
    // Append to last optgroup
    select.lastElementChild.appendChild(opt);
  }

  select.addEventListener("change", () => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "model_change", model: select.value }));
    }
  });

  container.appendChild(select);
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

// Stop Button: Audio stoppen, Spracherkennung abbrechen, Status reset
btnStop.addEventListener("click", () => {
  // Audio stoppen
  audioQueue = [];
  isPlayingAudio = false;
  document.querySelectorAll("audio").forEach((a) => { a.pause(); a.remove(); });

  // Spracherkennung stoppen
  if (recognition && isListening) {
    recognition.abort();
    isListening = false;
    btnTalk.classList.remove("recording");
  }

  setStatus("idle", "SYSTEMS ONLINE");
  responseText.classList.remove("visible");
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

// Clap Toggle
const btnClap = document.getElementById("btn-clap");
if (btnClap) {
  btnClap.addEventListener("click", () => {
    if (clapEnabled) {
      disableClap();
    } else {
      enableClap();
    }
  });
}

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
