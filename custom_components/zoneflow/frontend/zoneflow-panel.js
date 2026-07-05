/**
 * Panou ZoneFlow — web component vanilla (fără build step).
 * Tab-uri: Stare (info live), Zone (editor), Setări, Ajutor.
 * Citește/scrie prin comenzile websocket zoneflow/get|save_zones|save_general|run_now|stop.
 */

const TABS = [
  ["stare", "Stare"],
  ["zone", "Zone"],
  ["rapoarte", "Rapoarte"],
  ["setari", "Setări"],
  ["ajutor", "Ajutor"],
];

const fmtSecs = (s) => {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
};

const genId = () =>
  (window.crypto && crypto.randomUUID
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(16).slice(2, 10));

const esc = (s) =>
  String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
  );

const fmt = (v, unit = "", dec = 1) =>
  v == null || v === "" ? "—" : `${Number(v).toFixed(dec)}${unit}`;

class ZoneFlowPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "stare";
    this._data = null;
    this._zones = null;
    this._loaded = false;
    this._error = null;
    this._refresh = null;
    this._dirty = false;  // modificări nesalvate în editorul de zone
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  connectedCallback() {
    // Ticker 1s: cronometru live + reîmprospătare periodică a stării.
    this._ticks = 0;
    this._refresh = setInterval(() => this._tick(), 1000);
  }

  disconnectedCallback() {
    if (this._refresh) clearInterval(this._refresh);
  }

  _tick() {
    if (this._tab !== "stare" || !this._data) return;
    const w = (this._data.live || {}).watering || {};
    if (w.active && w.current) {
      const remEl = this.shadowRoot.getElementById("live-remaining");
      const remSec = (new Date(w.current.ends_at).getTime() - Date.now()) / 1000;
      if (remEl) remEl.textContent = fmtSecs(remSec);
      // Când expiră reprize/grupul, preluăm starea nouă (o singură dată).
      if (remSec <= 0 && !this._reloadingLive) {
        this._reloadingLive = true;
        this._reload(true).finally(() => { this._reloadingLive = false; });
      }
    } else if (++this._ticks % 30 === 0) {
      this._reload(true);
    }
  }

  async _ws(msg) {
    return this._hass.connection.sendMessagePromise(msg);
  }

  async _load() {
    try {
      this._data = await this._ws({ type: "zoneflow/get" });
      this._zones = JSON.parse(JSON.stringify(this._data.zones || []));
      this._dirty = false;
      this._error = null;
      // Auto-vindecare: dacă temperatura e goală la deschidere (ex. imediat după restart),
      // forțăm o reîmprospătare a prognozei o singură dată.
      if (!this._retriedTemp && this._data.live && this._data.live.avg_temp == null) {
        this._retriedTemp = true;
        try {
          await this._ws({ type: "zoneflow/refresh" });
          this._data = await this._ws({ type: "zoneflow/get" });
        } catch (e) { /* ignorăm */ }
      }
    } catch (e) {
      this._error = (e && e.message) || "Eroare la încărcare";
    }
    this._render();
  }

  async _reload(silent) {
    try {
      this._data = await this._ws({ type: "zoneflow/get" });
      if (!silent) this._zones = JSON.parse(JSON.stringify(this._data.zones || []));
      this._error = null;
      this._render();
    } catch (e) {
      this._error = (e && e.message) || "Eroare";
      this._render();
    }
  }

  // ----------------------------------------------------------------- render
  _render() {
    const tabs = TABS.map(
      ([id, label]) =>
        `<button class="tab ${this._tab === id ? "active" : ""}" data-tab="${id}">${label}</button>`
    ).join("");

    let body = "";
    if (this._error) body = `<div class="err">⚠️ ${esc(this._error)}</div>`;
    else if (!this._data) body = `<div class="muted">Se încarcă…</div>`;
    else if (this._tab === "stare") body = this._renderStare();
    else if (this._tab === "zone") body = this._renderZone();
    else if (this._tab === "rapoarte") body = this._renderRapoarte();
    else if (this._tab === "setari") body = this._renderSetari();
    else body = this._renderAjutor();

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="wrap">
        <h1>ZoneFlow</h1>
        <div class="tabs">${tabs}</div>
        <div class="body">${body}</div>
      </div>`;

    this.shadowRoot.querySelectorAll(".tab").forEach((b) =>
      b.addEventListener("click", () => {
        this._tab = b.dataset.tab;
        this._render();
        if (this._tab === "rapoarte") this._loadReport();
      })
    );
    this._wire();
  }

  _groupName(gid) {
    for (const z of this._data.zones || [])
      for (const g of z.groups || [])
        if (g.id === gid) return `${z.name} · ${g.name}`;
    return gid;
  }

  _renderStare() {
    const l = this._data.live || {};
    const rt = l.runtimes || {};
    const rows = Object.keys(rt)
      .map((gid) => `<tr><td>${esc(this._groupName(gid))}</td><td class="r">${fmt(rt[gid], " min")}</td></tr>`)
      .join("") || `<tr><td colspan="2" class="muted">Niciun grup configurat</td></tr>`;
    const nr = l.next_run ? new Date(l.next_run).toLocaleString() : "—";
    const lr = l.last_run ? new Date(l.last_run).toLocaleDateString() : "—";
    return `
      <div class="cards">
        <div class="card"><span>Media temperaturii</span><b>${fmt(l.avg_temp, " °C")}</b></div>
        <div class="card"><span>Țintă</span><b>${fmt(l.target_mm, " L/m²")}</b></div>
        <div class="card"><span>Ploaie prevăzută (24h)</span><b>${fmt(l.rain_forecast_mm, " mm")}</b></div>
        <div class="card"><span>Ploaie căzută (48h)</span><b>${fmt(l.rain_fallen_mm, " mm")}</b></div>
        <div class="card"><span>Țintă după ploaie</span><b>${fmt(l.effective_target_mm, " L/m²")}</b></div>
        <div class="card"><span>Apă pe sesiune</span><b>${fmt(l.liters, " L", 0)}</b></div>
        <div class="card"><span>Interval</span><b>${l.interval_days != null ? l.interval_days + " zile" : "—"}${l.auto_interval ? " (auto)" : ""}</b></div>
        <div class="card"><span>Ultima udare</span><b>${esc(lr)}</b></div>
        <div class="card"><span>Următoarea udare</span><b>${esc(nr)}</b></div>
      </div>
      ${this._renderLive(l)}
      ${l.will_skip ? `<div class="note">🌧️ Sesiunea se va sări — plouă cât ținta sau mai mult.</div>` : ""}
      ${l.skip_next ? `<div class="note">⏭️ Următoarea udare programată va fi sărită.</div>` : ""}
      <h3>Durata pe grup</h3>
      <table>${rows}</table>
      <div class="actions">
        <button class="btn primary" data-act="run">💧 Udă acum</button>
        <button class="btn" data-act="stop">⏹️ Oprește</button>
        <button class="btn" data-act="schedule">📅 Udă la următoarea oră</button>
        <button class="btn" data-act="postpone">⏳ Amână 1 zi</button>
        <button class="btn" data-act="skip-next">${l.skip_next ? "↩️ Anulează skip" : "⏭️ Sări următoarea"}</button>
        <button class="btn" data-act="refresh">↻ Reîmprospătează</button>
      </div>
      <p class="muted">„Udă la următoarea oră" face prima udare să pornească automat la „Ora de
      udare" (ex. la noapte), apoi continuă pe interval.</p>`;
  }

  _remain(endsAt) {
    if (!endsAt) return "—";
    return fmtSecs((new Date(endsAt).getTime() - Date.now()) / 1000);
  }

  _renderLive(l) {
    const w = l.watering || {};
    if (!w.active) return "";
    const cur = w.current;
    if (!cur) return `<div class="note ok">💧 Udare în curs…</div>`;
    const upcoming = (cur.upcoming || []).filter(Boolean).join(" → ") || "—";
    const phase = cur.phase === "soak" ? "pauză infiltrare" : "udare";
    const repr = cur.cycles > 1 ? ` · repriza ${cur.cycle}/${cur.cycles}` : "";
    return `
      <div class="live">
        <div class="live-head">💧 Acum: <b>${esc(cur.label)}</b> · ${phase}${repr}</div>
        <div class="live-rem">rămâne <b id="live-remaining">${this._remain(cur.ends_at)}</b></div>
        <div class="muted">Urmează: ${esc(upcoming)}</div>
      </div>`;
  }

  async _loadReport() {
    try {
      this._reportData = await this._ws({ type: "zoneflow/history" });
    } catch (e) {
      this._reportData = { error: (e && e.message) || "Eroare" };
    }
    if (this._tab === "rapoarte") this._render();
  }

  _renderRapoarte() {
    const r = this._reportData;
    if (!r) return `<div class="muted">Se încarcă rapoartele…</div>`;
    if (r.error) return `<div class="err">⚠️ ${esc(r.error)}</div>`;
    const t = r.totals || {};
    const byZone = (r.by_zone || [])
      .map((z) => `<tr><td>${esc(z.name)}</td><td class="r">${fmt(z.liters, " L", 0)}</td><td class="r">${fmt(z.minutes, " min", 0)}</td></tr>`)
      .join("") || `<tr><td colspan="3" class="muted">—</td></tr>`;
    const records = (r.records || [])
      .map((rec) => {
        const d = rec.ts ? new Date(rec.ts).toLocaleString() : "—";
        if (rec.type === "skip")
          return `<tr><td>${esc(d)}</td><td colspan="2" class="muted">⏭️ sărită — ${esc(rec.reason || "")}</td></tr>`;
        if (rec.type === "rain")
          return `<tr><td>${esc(d)}</td><td colspan="2" class="muted">🌧️ ploaia a ținut loc de udare — ${fmt(rec.mm, " mm", 0)}</td></tr>`;
        const zones = (rec.zones || []).map((z) => z.name).join(", ") || "—";
        return `<tr><td>${esc(d)}</td><td class="r">${fmt(rec.liters, " L", 0)}</td><td>${esc(zones)} (${fmt(rec.minutes, " min", 0)})</td></tr>`;
      })
      .join("") || `<tr><td colspan="3" class="muted">Nicio sesiune încă</td></tr>`;
    return `
      <div class="cards">
        <div class="card"><span>Apă azi</span><b>${fmt(t.today, " L", 0)}</b></div>
        <div class="card"><span>Apă 7 zile</span><b>${fmt(t.week, " L", 0)}</b></div>
        <div class="card"><span>Apă 30 zile</span><b>${fmt(t.month, " L", 0)}</b></div>
        <div class="card"><span>Total udări</span><b>${t.count != null ? t.count : "—"}</b></div>
        <div class="card"><span>Sărite (ploaie/manual)</span><b>${t.skipped != null ? t.skipped : "—"}</b></div>
      </div>
      <h3>Pe zonă (30 zile)</h3>
      <table>${byZone}</table>
      <h3>Istoric sesiuni</h3>
      <table>${records}</table>
      <div class="actions"><button class="btn" data-act="report-refresh">↻ Reîmprospătează</button></div>`;
  }

  _renderZone() {
    const zones = (this._zones || [])
      .map((z, zi) => this._renderZoneCard(z, zi))
      .join("") || `<div class="muted">Nicio zonă. Adaugă una mai jos.</div>`;
    return `
      <p class="muted">O <b>zonă</b> = o parte din grădină (suprafață + un factor % opțional, ex.
      umbră 70%). Un <b>grup</b> = supapele care pornesc deodată, cu <b>rata</b> măsurată la testul
      cu caserole (mm în testul de ${esc((this._data.general || {}).test_minutes || 10)} min).
      Durata = țintă / rată.</p>
      ${zones}
      <div class="savebar">
        <button class="btn" data-act="add-zone">➕ Adaugă zonă</button>
        <span id="zsave-status" class="dirty">${this._dirty ? "● modificări nesalvate" : ""}</span>
        <button class="btn primary" data-act="save-zones">💾 Salvează zonele</button>
      </div>`;
  }

  _renderZoneCard(z, zi) {
    const groups = (z.groups || []).map((g, gi) => this._renderGroup(z, zi, g, gi)).join("");
    return `
      <div class="zone">
        <div class="zone-head">
          <input class="zname" data-z="${zi}" data-f="zname" value="${esc(z.name)}" placeholder="Nume zonă"/>
          <button class="x" data-act="del-zone" data-z="${zi}">🗑️ Șterge zona</button>
        </div>
        <div class="row2">
          <label class="lbl">Suprafață (m²)
            <input data-z="${zi}" data-f="zarea" type="number" min="0" step="0.5" value="${esc(z.area != null ? z.area : 0)}" class="num"/></label>
          <label class="lbl">Factor zonă (%)
            <input data-z="${zi}" data-f="zfactor" type="number" min="0" max="200" step="5" value="${esc(z.factor_pct != null ? z.factor_pct : 100)}" class="num"/></label>
        </div>
        <div class="row2">
          <label class="lbl">Max ciclu (min, gol = global)
            <input data-z="${zi}" data-f="zmax" type="number" min="0" max="120" step="1" placeholder="global" value="${esc(z.max_cycle != null && z.max_cycle !== "" ? z.max_cycle : "")}" class="num"/></label>
          <label class="lbl">Soak (min, gol = global)
            <input data-z="${zi}" data-f="zsoak" type="number" min="0" max="120" step="1" placeholder="global" value="${esc(z.soak != null && z.soak !== "" ? z.soak : "")}" class="num"/></label>
        </div>
        <div class="sub">Grupuri (supape + rată)</div>
        ${groups}
        <button class="btn small" data-act="add-group" data-z="${zi}">➕ Grup</button>
        <div class="row" style="margin-top:8px;align-items:center;">
          <span class="muted">Test:</span>
          <input id="test-${zi}" type="number" min="1" max="60" step="1" value="3" class="num"/>
          <span class="unit">min</span>
          <button class="btn small" data-act="test-zone" data-z="${zi}">▶ Rulează</button>
        </div>
      </div>`;
  }

  _renderGroup(z, zi, g, gi) {
    const opts = (this._data.switches || [])
      .map(
        (sw) =>
          `<option value="${esc(sw.entity_id)}" ${
            (g.switches || []).includes(sw.entity_id) ? "selected" : ""
          }>${esc(sw.name)}</option>`
      )
      .join("");
    return `
      <div class="group">
        <div class="row">
          <input data-z="${zi}" data-g="${gi}" data-f="gname" value="${esc(g.name)}" placeholder="Nume grup"/>
          <button class="x" data-act="del-group" data-z="${zi}" data-g="${gi}">✕</button>
        </div>
        <label class="lbl">Supape (pornesc simultan)</label>
        <select multiple size="3" data-z="${zi}" data-g="${gi}" data-f="switches">${opts}</select>
        <label class="lbl">Rată caserolă (mm / test)
          <input data-z="${zi}" data-g="${gi}" data-f="grate" type="number" min="0" step="0.1" value="${esc(g.rate != null ? g.rate : "")}" class="num"/></label>
      </div>`;
  }

  _renderSetari() {
    const g = this._data.general || {};
    const weathers = (this._data.weathers || [])
      .map((w) => `<option value="${esc(w.entity_id)}" ${w.entity_id === g.weather_entity ? "selected" : ""}>${esc(w.name)}</option>`)
      .join("");
    const c = this._data.controls || {};
    const st = (eid) => (eid && this._hass.states[eid]) || null;
    const val = (eid, dflt) => { const s = st(eid); return s ? s.state : dflt; };
    const timeState = st(c.start_time);
    const enabledOn = st(c.enabled) && st(c.enabled).state === "on";
    const rainOn = st(c.rain_comp) && st(c.rain_comp).state === "on";
    const autoOn = st(c.auto_interval) ? st(c.auto_interval).state === "on" : true;
    const notifyOn = st(c.notify) ? st(c.notify).state === "on" : true;
    return `
      <h3>General</h3>
      <label class="lbl">Entitate weather (prognoză)</label>
      <select id="weather">${weathers}</select>
      <label class="lbl">Trimite notificări către (opțional — altfel doar în interfața HA)</label>
      <select id="notifyservice">
        <option value="" ${!g.notify_service ? "selected" : ""}>— doar în interfața HA (clopoțel) —</option>
        ${(this._data.notify_services || [])
          .map((s) => `<option value="${esc(s)}" ${s === g.notify_service ? "selected" : ""}>notify.${esc(s)}</option>`)
          .join("")}
      </select>
      <label class="lbl">Senzor de ploaie (opțional — altfel estimez din prognoza orei curente)</label>
      <select id="rainsensor">
        <option value="" ${!g.rain_sensor ? "selected" : ""}>— fără (folosesc prognoza) —</option>
        ${(this._data.sensors || [])
          .map((s) => `<option value="${esc(s.entity_id)}" ${s.entity_id === g.rain_sensor ? "selected" : ""}>${esc(s.name)}</option>`)
          .join("")}
      </select>
      <div class="row2">
        <label class="lbl">Durata testului (min)
          <input id="testmin" type="number" min="1" step="1" value="${esc(g.test_minutes)}" class="num"/></label>
        <label class="lbl">Zile prognoză
          <input id="fdays" type="number" min="1" max="14" step="1" value="${esc(g.forecast_days)}" class="num"/></label>
      </div>

      <h3>Cantitate & program</h3>
      <div class="row2">
        <label class="lbl">Țintă apă (L/m²)
          <input id="target" type="number" min="5" max="40" step="1" value="${esc(val(c.target, "15"))}" class="num"/></label>
        <label class="lbl">Ajustare globală (×)
          <input id="factor" type="number" min="0" max="3" step="0.05" value="${esc(val(c.factor, "1.0"))}" class="num"/></label>
        <label class="lbl">Ora de udare
          <input id="starttime" type="time" value="${esc(timeState ? timeState.state.slice(0,5) : "06:00")}"/></label>
      </div>
      <label class="chk"><input type="checkbox" data-ctrl="toggle" data-eid="${esc(c.enabled)}" ${enabledOn ? "checked" : ""}/> Irigație activă</label>
      <label class="chk"><input type="checkbox" data-ctrl="toggle" data-eid="${esc(c.rain_comp)}" ${rainOn ? "checked" : ""}/> Compensare ploaie</label>
      <label class="chk"><input type="checkbox" data-ctrl="toggle" data-eid="${esc(c.auto_interval)}" ${autoOn ? "checked" : ""}/> Interval automat (după temperatură)</label>
      <label class="chk"><input type="checkbox" data-ctrl="toggle" data-eid="${esc(c.notify)}" ${notifyOn ? "checked" : ""}/> Notificări (start/stop/sărit)</label>
      <label class="lbl">Interval manual (zile, când „automat" e oprit)
        <input id="interval" type="number" min="1" max="60" step="1" value="${esc(val(c.interval, "3"))}" class="num"/></label>

      <h3>Cycle &amp; soak (anti-băltire)</h3>
      <div class="row2">
        <label class="lbl">Minute max/ciclu (0 = oprit)
          <input id="maxcycle" type="number" min="0" max="120" step="1" value="${esc(val(c.max_cycle, "15"))}" class="num"/></label>
        <label class="lbl">Pauză infiltrare (min)
          <input id="soak" type="number" min="0" max="120" step="1" value="${esc(val(c.soak, "20"))}" class="num"/></label>
      </div>
      <button class="btn primary" data-act="save-general">💾 Salvează setările</button>
      <p class="muted">Cantitate fixă „rar și mult" (~15 L/m²). Cu „Interval automat", frecvența
      vine din temperatură: ≥25°C → la 3 zile (2×/săpt), 10-25°C → la 7 zile, &lt;10°C → la 14 zile.</p>`;
  }

  _renderAjutor() {
    return `
      <h3>Principiu: „rar și mult"</h3>
      <p>Udăm <b>rar și abundent</b> (~15 L/m²/udare) ca să umezim solul adânc (15-20 cm) →
      rădăcini profunde. Cantitatea e <b>fixă</b>; <b>temperatura decide frecvența</b>, nu cantitatea.</p>
      <h3>Cum gândești configurarea</h3>
      <ul class="help">
        <li><b>Zonă</b> = o parte din grădină, cu <b>suprafața</b> (m²) și un <b>factor %</b>
            (ex. front umbrit 70% → mai puțină apă).</li>
        <li><b>Grup</b> = supapele care <b>pornesc deodată</b> și le-ai măsurat <b>împreună</b>.
            Un circuit care pornește singur = un grup cu o supapă.</li>
        <li><b>Rata (mm)</b> = câți mm a adunat caserola cu supapele grupului pornite, în testul
            de X minute (din Setări). Mai multe caserole → pune media.</li>
      </ul>
      <h3>Cum se calculează</h3>
      <p>Țintă zonă = <b>Țintă (L/m²)</b> × ajustare globală × factor zonă − ploaie prevăzută.
      Durata fiecărui grup = țintă / rata lui (metoda testului cu caserole). Grupurile rulează pe
      rând; supapele dintr-un grup, simultan. Dacă durata e mare, <b>cycle &amp; soak</b> o împarte
      în reprize cu pauze, ca să nu băltească.</p>
      <h3>Frecvența (interval automat)</h3>
      <p>Din temperatura medie: <b>≥25°C → la 3 zile</b> (2×/săpt), <b>10-25°C → la 7 zile</b>
      (1×/săpt), <b>&lt;10°C → la 14 zile</b>. Poți trece pe interval manual din Setări.</p>
      <h3>Cycle &amp; soak per zonă</h3>
      <p>În <b>Setări</b> ai valorile globale (Minute max/ciclu + Pauză soak). În <b>Zone</b>,
      fiecare zonă poate avea propriile valori — lăsate <b>goale</b> folosesc globalul, o valoare
      le suprascrie doar pentru zona aceea, iar <b>0</b> dezactivează reprizele pentru acea zonă
      (ex. front argilos cu reprize scurte, restul pe global).</p>
      <h3>Amână / sări</h3>
      <p><b>⏳ Amână 1 zi</b> — pentru „testul cu șurubelnița": dacă dimineața șurubelnița intră
      ușor în sol (încă umed), amâni udarea cu o zi; mâine verifici din nou. Apăsat de mai multe
      ori → mai multe zile. <b>⏭️ Sări următoarea</b> mută udarea cu un <i>interval întreg</i>.</p>
      <h3>Notificări</h3>
      <p>Implicit, notificările (start/terminat/sărit) apar doar la <b>clopoțelul din interfața
      HA</b>. Ca să primești <b>push pe telefon</b>, alege în Setări serviciul aplicației
      companion (ex. <code>notify.mobile_app_telefonul_meu</code>) la „Trimite notificări către".</p>
      <h3>Ploaia căzută (registrul de ploaie)</h3>
      <p>Pe lângă prognoza pe 24h, ZoneFlow ține un <b>registru al ploii căzute</b>: în fiecare
      oră notează precipitația estimată pentru ora curentă (sau, dacă ai configurat un
      <b>senzor de ploaie</b> în Setări, valoarea reală măsurată). Ploaia din ultimele 48h
      <b>se scade din următoarea udare</b>; dacă a plouat cât ținta (ex. ≥15 mm), ploaia
      <b>contează ca o udare completă</b> și următoarea sesiune se mută cu un interval întreg.
      Creditul se golește după fiecare udare.</p>
      <h3>Furnizor de prognoză</h3>
      <p>ZoneFlow folosește o entitate <code>weather</code> aleasă în Setări (nu un furnizor
      propriu). Dacă „Media temperaturii" e goală, entitatea aleasă nu oferă prognoză cu
      temperatură — recomandat <b>Met.no</b> (built-in în HA, fără cheie). Butonul
      <b>Reîmprospătează</b> forțează recalcularea (re-interoghează prognoza).</p>`;
  }

  // ------------------------------------------------------------------- wire
  _wire() {
    const root = this.shadowRoot;

    // butoane cu data-act
    root.querySelectorAll("[data-act]").forEach((el) =>
      el.addEventListener("click", (e) => this._onAction(e.currentTarget.dataset.act, e.currentTarget.dataset))
    );

    // editare câmpuri zone (fără re-render, ca să nu pierzi focusul)
    root.querySelectorAll("input[data-f], select[data-f]").forEach((el) =>
      el.addEventListener(el.tagName === "SELECT" ? "change" : "input", (e) => this._onField(e.currentTarget))
    );

    // controale (toggle/zi)
    root.querySelectorAll("[data-ctrl]").forEach((el) =>
      el.addEventListener("change", (e) => this._onControl(e.currentTarget))
    );
  }

  _onField(el) {
    const d = el.dataset;
    const z = this._zones[+d.z];
    if (!z) return;
    if (d.f === "zname") z.name = el.value;
    else if (d.f === "zarea") z.area = parseFloat(el.value) || 0;
    else if (d.f === "zfactor") z.factor_pct = parseFloat(el.value) || 0;
    else if (d.f === "zmax") { if (el.value === "") delete z.max_cycle; else z.max_cycle = parseFloat(el.value) || 0; }
    else if (d.f === "zsoak") { if (el.value === "") delete z.soak; else z.soak = parseFloat(el.value) || 0; }
    else if (d.f === "gname") z.groups[+d.g].name = el.value;
    else if (d.f === "switches")
      z.groups[+d.g].switches = Array.from(el.selectedOptions).map((o) => o.value);
    else if (d.f === "grate") z.groups[+d.g].rate = parseFloat(el.value) || 0;
    this._markDirty();
  }

  _markDirty() {
    this._dirty = true;
    const s = this.shadowRoot.getElementById("zsave-status");
    if (s) s.textContent = "● modificări nesalvate";
  }

  async _onControl(el) {
    const eid = el.dataset.eid;
    if (!eid || eid === "null") return;
    if (el.dataset.ctrl === "toggle") {
      await this._hass.callService("switch", el.checked ? "turn_on" : "turn_off", { entity_id: eid });
    }
  }

  async _onAction(act, d) {
    try {
      if (act === "run") return void (await this._ws({ type: "zoneflow/run_now" }), this._reload(true));
      if (act === "stop") return void (await this._ws({ type: "zoneflow/stop" }), this._reload(true));
      if (act === "refresh") {
        await this._ws({ type: "zoneflow/refresh" });  // forțează re-interogarea prognozei
        return void this._reload(true);
      }
      if (act === "schedule") {
        await this._ws({ type: "zoneflow/schedule_due" });
        this._toast("Prima udare va porni la următoarea oră programată.");
        return void this._reload(true);
      }
      if (act === "skip-next") {
        await this._ws({ type: "zoneflow/skip_next" });
        return void this._reload(true);
      }
      if (act === "postpone") {
        await this._ws({ type: "zoneflow/postpone" });
        this._toast("Udarea a fost amânată cu o zi.");
        return void this._reload(true);
      }
      if (act === "report-refresh") return void this._loadReport();
      if (act === "test-zone") {
        const z = this._zones[+d.z];
        const inp = this.shadowRoot.getElementById(`test-${d.z}`);
        const minutes = parseFloat(inp && inp.value) || 3;
        await this._ws({ type: "zoneflow/test_zone", zone_id: z.id, minutes });
        this._toast(`Test ${z.name}: ${minutes} min.`);
        this._tab = "stare";
        return void this._reload(true);
      }

      if (act === "add-zone") {
        this._zones.push({ id: genId(), name: "Zonă nouă", area: 0, factor_pct: 100, groups: [] });
        this._dirty = true;
        return this._render();
      }
      if (act === "del-zone") { this._zones.splice(+d.z, 1); this._dirty = true; return this._render(); }
      if (act === "add-group") {
        this._zones[+d.z].groups.push({ id: genId(), name: "Grup", switches: [], rate: 10 });
        this._dirty = true;
        return this._render();
      }
      if (act === "del-group") { this._zones[+d.z].groups.splice(+d.g, 1); this._dirty = true; return this._render(); }

      if (act === "save-zones") {
        await this._ws({ type: "zoneflow/save_zones", zones: this._zones });
        this._dirty = false;
        this._toast("Zonele au fost salvate.");
        return this._reload(true);
      }
      if (act === "save-general") {
        const c = this._data.controls || {};
        const setNum = async (eid, id) => {
          const v = this.shadowRoot.getElementById(id);
          if (eid && v && v.value !== "") await this._hass.callService("number", "set_value", { entity_id: eid, value: parseFloat(v.value) });
        };
        // 1) Întâi setăm entitățile (ora + numere), ca să nu se piardă la reload.
        const t = this.shadowRoot.getElementById("starttime").value;
        if (c.start_time && t) await this._hass.callService("time", "set_value", { entity_id: c.start_time, time: t.length === 5 ? t + ":00" : t });
        await setNum(c.target, "target");
        await setNum(c.factor, "factor");
        await setNum(c.interval, "interval");
        await setNum(c.max_cycle, "maxcycle");
        await setNum(c.soak, "soak");
        // 2) Apoi setările generale (weather/test/forecast) — declanșează reload, la final.
        const weather = this.shadowRoot.getElementById("weather").value;
        const testmin = parseFloat(this.shadowRoot.getElementById("testmin").value) || 10;
        const fdays = parseInt(this.shadowRoot.getElementById("fdays").value) || 7;
        const rainsensor = this.shadowRoot.getElementById("rainsensor").value || null;
        const notifyservice = this.shadowRoot.getElementById("notifyservice").value || null;
        await this._ws({ type: "zoneflow/save_general", weather_entity: weather, test_minutes: testmin, forecast_days: fdays, rain_sensor: rainsensor, notify_service: notifyservice });
        this._toast("Setările au fost salvate.");
        return this._reload(true);
      }
    } catch (e) {
      this._toast("Eroare: " + ((e && e.message) || e), true);
    }
  }

  _toast(msg, err) {
    const t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText = `position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 16px;border-radius:8px;color:#fff;z-index:9999;background:${err ? "#b00020" : "#2e7d32"}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2600);
  }
}

const STYLE = `
  :host{display:block;color:var(--primary-text-color,#e1e1e1);font-family:var(--paper-font-body1_-_font-family,sans-serif);}
  .wrap{max-width:880px;margin:0 auto;padding:16px;}
  h1{font-size:22px;margin:8px 0 16px;}
  h3{margin:20px 0 8px;border-bottom:1px solid var(--divider-color,#333);padding-bottom:4px;}
  .tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:16px;}
  .tab{padding:8px 16px;border:none;border-radius:8px 8px 0 0;background:var(--card-background-color,#1c1c1c);color:inherit;cursor:pointer;}
  .tab.active{background:var(--primary-color,#03a9f4);color:#fff;}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;}
  .card{background:var(--card-background-color,#1c1c1c);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:4px;}
  .card span{font-size:12px;opacity:.7;} .card b{font-size:20px;}
  table{width:100%;border-collapse:collapse;} td{padding:6px 4px;border-bottom:1px solid var(--divider-color,#2a2a2a);}
  td.r{text-align:right;font-variant-numeric:tabular-nums;}
  .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px;}
  .savebar{position:sticky;bottom:0;display:flex;gap:8px;align-items:center;margin-top:12px;padding:10px 14px;background:var(--card-background-color,#1c1c1c);border-top:1px solid var(--divider-color,#333);}
  .dirty{flex:1;text-align:right;color:#ffb300;font-size:13px;}
  .btn{padding:9px 14px;border:1px solid var(--divider-color,#444);border-radius:8px;background:var(--card-background-color,#1c1c1c);color:inherit;cursor:pointer;}
  .btn.primary{background:var(--primary-color,#03a9f4);color:#fff;border-color:transparent;}
  .btn.small{padding:5px 10px;font-size:13px;margin:4px 0 8px;}
  .zone{background:var(--card-background-color,#1c1c1c);border-radius:12px;padding:14px;margin-bottom:14px;}
  .zone-head{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:8px;}
  .zname{font-size:17px;font-weight:600;flex:1;}
  .sub{font-size:12px;text-transform:uppercase;opacity:.6;margin:12px 0 6px;}
  .group{border:1px solid var(--divider-color,#333);border-radius:8px;padding:10px;margin-bottom:8px;}
  .row{display:flex;gap:8px;align-items:center;margin-bottom:6px;}
  .row2{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0;}
  input,select{background:var(--secondary-background-color,#111);color:inherit;border:1px solid var(--divider-color,#444);border-radius:6px;padding:7px 8px;font:inherit;flex:1;min-width:0;}
  input.num{flex:0 0 90px;text-align:right;}
  .unit{opacity:.6;font-size:13px;}
  .lbl{display:block;font-size:13px;opacity:.8;margin:8px 0 4px;}
  .rates{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px;}
  .rate{display:flex;align-items:center;gap:6px;font-size:13px;}
  .rate input{flex:0 0 80px;}
  .chk{display:flex;align-items:center;gap:8px;margin:6px 0;}
  .chk input{flex:0 0 auto;}
  .days{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:4px;}
  .x{background:transparent;border:none;color:#e57373;cursor:pointer;font-size:14px;flex:0 0 auto;}
  .muted{opacity:.6;} .err{color:#e57373;padding:10px;}
  .note{background:rgba(3,169,244,.12);border-radius:8px;padding:8px 12px;margin:10px 0;}
  .note.ok{background:rgba(46,125,50,.18);}
  .live{background:rgba(3,169,244,.16);border:1px solid var(--primary-color,#03a9f4);border-radius:10px;padding:12px 14px;margin:12px 0;}
  .live-head{font-size:15px;} .live-rem{font-size:22px;margin:4px 0;font-variant-numeric:tabular-nums;}
  ul.help{line-height:1.5;} ul.help li{margin-bottom:6px;}
  p.muted{line-height:1.5;}
`;

customElements.define("zoneflow-panel", ZoneFlowPanel);
