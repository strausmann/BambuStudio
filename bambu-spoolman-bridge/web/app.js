// Bambu <-> Spoolman Bridge PWA (Tailwind). Prototype.
const hasNFC = "NDEFReader" in window;
const hasQR = "BarcodeDetector" in window;
document.getElementById("caps").textContent = `NFC ${hasNFC ? "✓" : "✗"} · QR ${hasQR ? "✓" : "✗"}`;

async function api(path, opts) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
const el = (id) => document.getElementById(id);
const dot = (h) => `<span class="inline-block w-3 h-3 rounded-full align-middle mr-1 border border-black/20" style="background:#${(h||'888').replace('#','').slice(0,6)}"></span>`;

// ---- tabs ----------------------------------------------------------------
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((t) => t.className = "tab px-3 py-1.5 rounded-lg bg-slate-200 dark:bg-slate-700");
  b.className = "tab px-3 py-1.5 rounded-lg bg-emerald-600 text-white";
  document.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.panel !== b.dataset.tab));
}));

// ---- onboarding ----------------------------------------------------------
async function refresh() {
  let s; try { s = await api("/api/state"); } catch { return; }
  const pend = el("pending");
  pend.innerHTML = s.pending.length ? "" : '<p class="text-sm opacity-60">Keine offenen Spulen.</p>';
  for (const p of s.pending) {
    const c = document.createElement("div");
    c.className = "rounded-lg border border-slate-200 dark:border-slate-700 p-3";
    c.innerHTML = `<div class="font-medium">${dot(p.color)}${p.material} <span class="opacity-50 text-sm">(${p.setting_id||'?'})</span></div>
      <div class="text-xs opacity-70">Tag ${p.tag_uid} · ${p.slot} · remain ${p.remain}%</div>`;
    const row = document.createElement("div"); row.className = "flex gap-2 mt-2";
    const b1 = document.createElement("button"); b1.className = "px-3 py-1 rounded-lg bg-emerald-600 text-white text-sm"; b1.textContent = "Zuordnen (QR)"; b1.onclick = () => openBind(p);
    const b2 = document.createElement("button"); b2.className = "px-3 py-1 rounded-lg bg-slate-200 dark:bg-slate-700 text-sm"; b2.textContent = "Auto-anlegen";
    b2.onclick = async () => { try { const r = await api("/api/onboard_auto", { method: "POST", body: JSON.stringify({ tag_uid: p.tag_uid }) }); alert("Spule #" + r.spool_id + " angelegt."); refresh(); } catch (e) { alert(e.message); } };
    row.append(b1, b2); c.append(row); pend.append(c);
  }
  el("free").innerHTML = s.free_tags.length ? s.free_tags.map((t) =>
    `<div class="rounded-lg border border-slate-200 dark:border-slate-700 p-2 text-sm">${dot(t.meta_color)}${t.meta_material||'?'} · Tag ${t.tag_uid} · ${t.meta_temp_min||'?'}–${t.meta_temp_max||'?'}°C</div>`).join("") : '<p class="text-sm opacity-60">—</p>';
  el("ams").innerHTML = (s.ams && s.ams.length) ? s.ams.map((a) => `${a.type} (SN …${(a.sn||'').slice(-4)}) · AMS${a.ams_id}`).join("<br>") : "—";
}

// ---- bind dialog + QR ----------------------------------------------------
const dlg = el("bind-dlg"); let bindTag = null;
function openBind(p) { bindTag = p.tag_uid; el("bind-info").textContent = `Tag ${p.tag_uid} — ${p.material} ${p.color}`; el("bind-spool").value = ""; el("bind-scaninfo").textContent = ""; dlg.showModal(); }
el("bind-ok").addEventListener("click", async (e) => {
  const id = parseInt(el("bind-spool").value, 10); if (!bindTag || !id) return; e.preventDefault();
  try { await api("/api/bind", { method: "POST", body: JSON.stringify({ tag_uid: bindTag, spool_id: id }) }); dlg.close(); refresh(); }
  catch (err) { alert("Bind: " + err.message); }
});
function spoolIdFromText(t) { const m = String(t).match(/spool\/(\d+)/i) || String(t).match(/(\d+)\s*$/); return m ? parseInt(m[1], 10) : null; }
el("bind-scan").addEventListener("click", async () => {
  if (!hasQR) { el("bind-scaninfo").textContent = "BarcodeDetector n/a"; return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    const v = document.createElement("video"); v.srcObject = stream; await v.play();
    const det = new BarcodeDetector({ formats: ["qr_code"] }); el("bind-scaninfo").textContent = "scanne…";
    const tick = async () => {
      const codes = await det.detect(v).catch(() => []);
      if (codes.length) { const id = spoolIdFromText(codes[0].rawValue); stream.getTracks().forEach((t) => t.stop());
        if (id) { el("bind-spool").value = id; el("bind-scaninfo").textContent = "QR: " + id; } else el("bind-scaninfo").textContent = "kein /spool/{id}"; return; }
      requestAnimationFrame(tick);
    }; tick();
  } catch { el("bind-scaninfo").textContent = "Kamera-Fehler"; }
});

// ---- SpoolmanDB ----------------------------------------------------------
const selVendors = new Set(), selTypes = new Set();
function chip(label, set) {
  const b = document.createElement("button");
  const paint = () => b.className = "px-2 py-1 rounded-md text-xs " + (set.has(label) ? "bg-emerald-600 text-white" : "bg-slate-200 dark:bg-slate-700");
  b.textContent = label; paint();
  b.onclick = () => { set.has(label) ? set.delete(label) : set.add(label); paint(); };
  return b;
}
el("spdb-load").addEventListener("click", async () => {
  el("spdb-meta").textContent = "lädt…";
  try {
    const s = await api("/api/spoolmandb/summary");
    el("spdb-meta").textContent = `${s.count} Einträge · ${s.vendors.length} Hersteller · ${s.types.length} Typen`;
    el("spdb-vendors").innerHTML = ""; s.vendors.forEach((v) => el("spdb-vendors").append(chip(v, selVendors)));
    el("spdb-types").innerHTML = ""; s.types.forEach((t) => el("spdb-types").append(chip(t, selTypes)));
  } catch (e) { el("spdb-meta").textContent = "Fehler: " + e.message; }
});
async function spdbImport(dry) {
  el("spdb-out").textContent = dry ? "Vorschau…" : "Import…";
  try {
    const r = await api("/api/spoolmandb/import", { method: "POST", body: JSON.stringify({ vendors: [...selVendors], types: [...selTypes], dry_run: dry }) });
    el("spdb-out").textContent = JSON.stringify(r, null, 2);
  } catch (e) { el("spdb-out").textContent = "Fehler: " + e.message; }
}
el("spdb-dry").addEventListener("click", () => spdbImport(true));
el("spdb-import").addEventListener("click", () => spdbImport(false));

// ---- preset generator ----------------------------------------------------
let lastPreset = null;
el("p-gen").addEventListener("click", async () => {
  const num = (id) => { const v = el(id).value.trim(); return v === "" ? null : Number(v); };
  const body = {
    vendor: el("p-vendor").value, material: el("p-material").value, name: el("p-name").value,
    color_hex: el("p-color").value, nozzle_temp: num("p-nozzle"), bed_temp: num("p-bed"),
    flow_ratio: num("p-flow"), density: num("p-density"), max_vol_speed: num("p-vol"),
    diameter: 1.75, compatible_printer: el("p-printer").value,
  };
  try {
    lastPreset = await api("/api/preset/generate", { method: "POST", body: JSON.stringify(body) });
    el("p-out").textContent = JSON.stringify(lastPreset, null, 2); el("p-dl").classList.remove("hidden");
  } catch (e) { el("p-out").textContent = "Fehler: " + e.message; }
});
el("p-dl").addEventListener("click", () => {
  if (!lastPreset) return;
  const blob = new Blob([JSON.stringify(lastPreset, null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = (lastPreset.name || "filament") + ".json"; a.click();
});

// ---- cloud import --------------------------------------------------------
async function cloudImport(dry) {
  el("cloud-out").textContent = dry ? "Dry-Run…" : "Import…";
  try { el("cloud-out").textContent = JSON.stringify(await api("/api/cloud/import", { method: "POST", body: JSON.stringify({ source: "live", dry_run: dry }) }), null, 2); }
  catch (e) { el("cloud-out").textContent = "Fehler: " + e.message; }
}
el("cloud-dry").addEventListener("click", () => cloudImport(true));
el("cloud-import").addEventListener("click", () => cloudImport(false));

// ---- NFC -----------------------------------------------------------------
el("nfc-read").addEventListener("click", async () => {
  if (!hasNFC) { el("nfc-out").textContent = "Web NFC n/a (HTTPS + Android Chrome)"; return; }
  try { const r = new NDEFReader(); await r.scan(); el("nfc-out").textContent = "Tag anhalten…";
    r.onreading = (ev) => { for (const rec of ev.message.records) if (rec.recordType === "text" || rec.mediaType === "application/json") el("nfc-out").textContent = new TextDecoder().decode(rec.data); };
  } catch (e) { el("nfc-out").textContent = "Lesefehler: " + e.message; }
});
el("nfc-write").addEventListener("click", async () => {
  if (!hasNFC) { alert("Web NFC n/a"); return; }
  const payload = { protocol: "openspool", version: "1.0", type: el("w-type").value, color_hex: el("w-color").value, brand: el("w-brand").value, min_temp: el("w-min").value, max_temp: el("w-max").value, spoolman_id: el("w-spool").value };
  try { await new NDEFReader().write({ records: [{ recordType: "mime", mediaType: "application/json", data: new TextEncoder().encode(JSON.stringify(payload)) }] }); alert("Tag geschrieben."); }
  catch (e) { alert("Schreibfehler: " + e.message); }
});

refresh(); setInterval(refresh, 5000);
