// Bambu <-> Spoolman Bridge PWA (prototype).
// - polls /api/state for pending onboarding + free tags
// - Web NFC: read/write custom OpenSpool NDEF tags (same format as the ESP32)
// - QR scan (BarcodeDetector) to quick-bind a tag to a Spoolman spool URL
//
// NOTE: Web NFC + camera require a secure context (HTTPS). Behind Pangolin/
// Traefik/NPM/Caddy this works; over a plain LAN http:// URL it does not.

const hasNFC = "NDEFReader" in window;
const hasQR = "BarcodeDetector" in window;
document.getElementById("caps").textContent =
  `NFC: ${hasNFC ? "✓" : "✗"} · QR: ${hasQR ? "✓" : "✗"}`;

async function api(path, opts) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function colorDot(hex) {
  const c = (hex || "").replace("#", "").slice(0, 6) || "888";
  return `<span class="dot" style="background:#${c}"></span>`;
}

// ---- render --------------------------------------------------------------
async function refresh() {
  let state;
  try { state = await api("/api/state"); }
  catch (e) { return; }

  const pend = document.getElementById("pending");
  pend.innerHTML = state.pending.length ? "" : '<p class="muted">Keine offenen Spulen.</p>';
  for (const p of state.pending) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<div class="t">${colorDot(p.color)}${p.material} <small>(${p.setting_id})</small></div>
      <div class="s">Tag ${p.tag_uid} · ${p.slot} · remain ${p.remain}%</div>`;
    const btn = document.createElement("button");
    btn.textContent = "Zuordnen";
    btn.onclick = () => openBind(p);
    el.appendChild(btn);
    pend.appendChild(el);
  }

  const free = document.getElementById("free");
  free.innerHTML = state.free_tags.length ? "" : '<p class="muted">—</p>';
  for (const t of state.free_tags) {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<div class="t">${colorDot(t.meta_color)}${t.meta_material || "?"}</div>
      <div class="s">Tag ${t.tag_uid} · ${t.meta_temp_min || "?"}–${t.meta_temp_max || "?"}°C</div>`;
    free.appendChild(el);
  }
}

// ---- bind dialog + QR ----------------------------------------------------
const dlg = document.getElementById("bind-dlg");
let bindTag = null;

function openBind(p) {
  bindTag = p.tag_uid;
  document.getElementById("bind-info").textContent =
    `Tag ${p.tag_uid} — ${p.material} ${p.color}`;
  document.getElementById("bind-spool").value = "";
  document.getElementById("bind-scaninfo").textContent = "";
  dlg.showModal();
}

document.getElementById("bind-ok").addEventListener("click", async (e) => {
  const id = parseInt(document.getElementById("bind-spool").value, 10);
  if (!bindTag || !id) return;
  e.preventDefault();
  try {
    await api("/api/bind", { method: "POST", body: JSON.stringify({ tag_uid: bindTag, spool_id: id }) });
    dlg.close();
    refresh();
  } catch (err) { alert("Bind fehlgeschlagen: " + err.message); }
});

// Parse a Spoolman spool URL like .../spool/123 -> 123
function spoolIdFromText(text) {
  const m = String(text).match(/spool\/(\d+)/i) || String(text).match(/(\d+)\s*$/);
  return m ? parseInt(m[1], 10) : null;
}

document.getElementById("bind-scan").addEventListener("click", async () => {
  if (!hasQR) { document.getElementById("bind-scaninfo").textContent = "BarcodeDetector n/a"; return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const video = document.createElement("video");
    video.srcObject = stream; await video.play();
    const detector = new BarcodeDetector({ formats: ["qr_code"] });
    const info = document.getElementById("bind-scaninfo");
    info.textContent = "scanne…";
    const tick = async () => {
      const codes = await detector.detect(video).catch(() => []);
      if (codes.length) {
        const id = spoolIdFromText(codes[0].rawValue);
        stream.getTracks().forEach((t) => t.stop());
        if (id) { document.getElementById("bind-spool").value = id; info.textContent = "QR: " + id; }
        else info.textContent = "kein /spool/{id} im QR";
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  } catch (e) { document.getElementById("bind-scaninfo").textContent = "Kamera-Fehler"; }
});

// ---- Web NFC: custom OpenSpool tags --------------------------------------
document.getElementById("nfc-read").addEventListener("click", async () => {
  const out = document.getElementById("nfc-out");
  if (!hasNFC) { out.textContent = "Web NFC n/a (HTTPS + Android Chrome nötig)"; return; }
  try {
    const reader = new NDEFReader();
    await reader.scan();
    out.textContent = "Tag an das Gerät halten…";
    reader.onreading = (ev) => {
      for (const rec of ev.message.records) {
        if (rec.recordType === "text" || rec.mediaType === "application/json") {
          const txt = new TextDecoder().decode(rec.data);
          out.textContent = txt;
        }
      }
    };
  } catch (e) { out.textContent = "Lesefehler: " + e.message; }
});

document.getElementById("nfc-write").addEventListener("click", async () => {
  if (!hasNFC) { alert("Web NFC n/a"); return; }
  const payload = {
    protocol: "openspool",
    version: "1.0",
    type: document.getElementById("w-type").value,
    color_hex: document.getElementById("w-color").value,
    brand: document.getElementById("w-brand").value,
    min_temp: document.getElementById("w-min").value,
    max_temp: document.getElementById("w-max").value,
    spoolman_id: document.getElementById("w-spool").value, // our extension for binding
  };
  try {
    const writer = new NDEFReader();
    await writer.write({
      records: [{ recordType: "mime", mediaType: "application/json",
                  data: new TextEncoder().encode(JSON.stringify(payload)) }],
    });
    alert("Tag geschrieben.");
  } catch (e) { alert("Schreibfehler: " + e.message); }
});

refresh();
setInterval(refresh, 5000);
