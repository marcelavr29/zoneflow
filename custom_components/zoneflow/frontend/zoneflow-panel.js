/**
 * Panou ZoneFlow — web component vanilla (fără build step).
 * Tab-uri: Stare (info live), Zone (editor), Setări, Ajutor.
 * Citește/scrie prin comenzile websocket zoneflow/get|save_zones|save_general|run_now|stop.
 */

const TABS = [
  ["stare", "Stare"],
  ["zone", "Zone"],
  ["setari", "Setări"],
  ["ajutor", "Ajutor"],
];

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
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  connectedCallback() {
    // reîmprospătare periodică a stării (nu re-randa în timpul editării zonelor)
    this._refresh = setInterval(() => {
      if (this._tab === "stare") this._reload(true);
    }, 30000);
  }

  disconnectedCallback() {
    if (this._refresh) clearInterval(this._refresh);
  }

  async _ws(msg) {
    return this._hass.connection.sendMessagePromise(msg);
  }

  async _load() {
    try {
      this._data = await this._ws({ type: "zoneflow/get" });
      this._zones = JSON.parse(JSON.stringify(this._data.zones || []));
      this._error = null;
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
        <div class="card"><span>Țintă după ploaie</span><b>${fmt(l.effective_target_mm, " L/m²")}</b></div>
        <div class="card"><span>Apă pe sesiune</span><b>${fmt(l.liters, " L", 0)}</b></div>
        <div class="card"><span>Interval</span><b>${l.interval_days != null ? l.interval_days + " zile" : "—"}</b></div>
        <div class="card"><span>Ultima udare</span><b>${esc(lr)}</b></div>
        <div class="card"><span>Următoarea udare</span><b>${esc(nr)}</b></div>
      </div>
      ${l.will_skip ? `<div class="note">🌧️ Sesiunea se va sări — plouă cât ținta sau mai mult.</div>` : ""}
      ${l.is_watering ? `<div class="note ok">💧 Udare în curs…</div>` : ""}
      <h3>Durata pe grup</h3>
      <table>${rows}</table>
      <div class="actions">
        <button class="btn primary" data-act="run">💧 Udă acum</button>
        <button class="btn" data-act="stop">⏹️ Oprește</button>
        <button class="btn" data-act="refresh">↻ Reîmprospătează</button>
      </div>`;
  }

  _renderZone() {
    const zones = (this._zones || [])
      .map((z, zi) => this._renderZoneCard(z, zi))
      .join("") || `<div class="muted">Nicio zonă. Adaugă una mai jos.</div>`;
    return `
      <p class="muted">O <b>porțiune</b> = sub-zonă care trebuie udată la fel. Un <b>grup</b> =
      supapele care pornesc deodată (și pe care le-ai măsurat împreună). Pune rata în mm pe
      fiecare porțiune; 0 dacă grupul nu ajunge acolo.</p>
      ${zones}
      <div class="actions">
        <button class="btn" data-act="add-zone">➕ Adaugă zonă</button>
        <button class="btn primary" data-act="save-zones">💾 Salvează zonele</button>
      </div>`;
  }

  _renderZoneCard(z, zi) {
    const sections = (z.sections || [])
      .map(
        (s, si) => `
        <div class="row">
          <input data-z="${zi}" data-s="${si}" data-f="sname" value="${esc(s.name)}" placeholder="Nume porțiune"/>
          <input data-z="${zi}" data-s="${si}" data-f="sarea" type="number" min="0" step="0.5" value="${esc(s.area)}" placeholder="m²" class="num"/>
          <span class="unit">m²</span>
          <button class="x" data-act="del-section" data-z="${zi}" data-s="${si}">✕</button>
        </div>`
      )
      .join("");

    const groups = (z.groups || []).map((g, gi) => this._renderGroup(z, zi, g, gi)).join("");

    return `
      <div class="zone">
        <div class="zone-head">
          <input class="zname" data-z="${zi}" data-f="zname" value="${esc(z.name)}" placeholder="Nume zonă"/>
          <button class="x" data-act="del-zone" data-z="${zi}">🗑️ Șterge zona</button>
        </div>
        <div class="sub">Porțiuni</div>
        ${sections}
        <button class="btn small" data-act="add-section" data-z="${zi}">➕ Porțiune</button>
        <div class="sub">Grupuri</div>
        ${groups}
        <button class="btn small" data-act="add-group" data-z="${zi}">➕ Grup</button>
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
    const rates = (z.sections || [])
      .map(
        (s) => `
        <label class="rate">${esc(s.name)}
          <input data-z="${zi}" data-g="${gi}" data-sec="${esc(s.id)}" data-f="rate" type="number" min="0" step="0.1"
                 value="${esc(g.rates && g.rates[s.id] != null ? g.rates[s.id] : "")}" class="num"/> mm
        </label>`
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
        <div class="rates">${rates}</div>
      </div>`;
  }

  _renderSetari() {
    const g = this._data.general || {};
    const weathers = (this._data.weathers || [])
      .map((w) => `<option value="${esc(w.entity_id)}" ${w.entity_id === g.weather_entity ? "selected" : ""}>${esc(w.name)}</option>`)
      .join("");
    const c = this._data.controls || {};
    const st = (eid) => (eid && this._hass.states[eid]) || null;
    const timeState = st(c.start_time);
    const factorState = st(c.factor);
    const enabledOn = st(c.enabled) && st(c.enabled).state === "on";
    const rainOn = st(c.rain_comp) && st(c.rain_comp).state === "on";
    const intervalState = st(c.interval);
    return `
      <h3>General</h3>
      <label class="lbl">Entitate weather (prognoză)</label>
      <select id="weather">${weathers}</select>
      <div class="row2">
        <label class="lbl">Durata testului (min)
          <input id="testmin" type="number" min="1" step="1" value="${esc(g.test_minutes)}" class="num"/></label>
        <label class="lbl">Zile prognoză
          <input id="fdays" type="number" min="1" max="14" step="1" value="${esc(g.forecast_days)}" class="num"/></label>
      </div>
      <button class="btn primary" data-act="save-general">💾 Salvează setările generale</button>

      <h3>Program & reglaje</h3>
      <label class="chk"><input type="checkbox" data-ctrl="toggle" data-eid="${esc(c.enabled)}" ${enabledOn ? "checked" : ""}/> Irigație activă</label>
      <label class="chk"><input type="checkbox" data-ctrl="toggle" data-eid="${esc(c.rain_comp)}" ${rainOn ? "checked" : ""}/> Compensare ploaie</label>
      <div class="row2">
        <label class="lbl">Ora de udare
          <input id="starttime" type="time" value="${esc(timeState ? timeState.state.slice(0,5) : "06:00")}"/></label>
        <label class="lbl">Interval între udări (zile)
          <input id="interval" type="number" min="1" max="60" step="1" value="${esc(intervalState ? intervalState.state : "2")}" class="num"/></label>
        <label class="lbl">Factor corecție
          <input id="factor" type="number" min="0" max="3" step="0.05" value="${esc(factorState ? factorState.state : "1.0")}" class="num"/></label>
      </div>
      <p class="muted">Udarea pornește la „Ora de udare", apoi din nou după intervalul setat,
      numărat de la ultima udare reală.</p>`;
  }

  _renderAjutor() {
    return `
      <h3>Cum gândești configurarea</h3>
      <ul class="help">
        <li><b>Zonă</b> = o parte din grădină (ex. „Față", „Spate").</li>
        <li><b>Porțiune</b> = o sub-zonă care trebuie udată la aceeași cantitate. Majoritatea
            zonelor au o singură porțiune („Toată zona"). Adaugi mai multe doar dacă o parte e
            udată diferit (ex. „interior" și „margine").</li>
        <li><b>Grup</b> = supapele care <b>pornesc deodată</b> și pe care le-ai măsurat
            <b>împreună</b> la testul cu caserole. Un circuit care pornește singur = un grup cu
            o supapă.</li>
        <li><b>Rata (mm)</b> = câți mm a adunat caserola pe acea porțiune, cu supapele grupului
            pornite, în testul de X minute (durata din Setări). Mai multe caserole → pune media.
            0 dacă grupul nu ajunge la porțiune.</li>
      </ul>
      <h3>Cum se calculează</h3>
      <p>Ținta = media temperaturii săptămânale (ex. 25°C → 25 L/m²), minus ploaia prevăzută.
      ZoneFlow rezolvă cât rulează fiecare grup ca fiecare porțiune să primească ținta.
      Grupurile rulează pe rând; supapele dintr-un grup pornesc simultan.</p>
      <h3>Exemple</h3>
      <ul class="help">
        <li><b>Față</b> (2 supape care stropesc tot, pornite deodată): o porțiune + un grup cu
            ambele supape + o rată.</li>
        <li><b>Spate</b> (mijloc + margine): două porțiuni („Interior", „Margine"); grup „Mijloc"
            cu rată în ambele, grup „Margine" cu rată doar în „Margine".</li>
      </ul>
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
    else if (d.f === "sname") z.sections[+d.s].name = el.value;
    else if (d.f === "sarea") z.sections[+d.s].area = parseFloat(el.value) || 0;
    else if (d.f === "gname") z.groups[+d.g].name = el.value;
    else if (d.f === "switches")
      z.groups[+d.g].switches = Array.from(el.selectedOptions).map((o) => o.value);
    else if (d.f === "rate") {
      const g = z.groups[+d.g];
      g.rates = g.rates || {};
      if (el.value === "") delete g.rates[d.sec];
      else g.rates[d.sec] = parseFloat(el.value) || 0;
    }
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

      if (act === "add-zone") {
        this._zones.push({ id: genId(), name: "Zonă nouă", sections: [{ id: genId(), name: "Toată zona", area: 0 }], groups: [] });
        return this._render();
      }
      if (act === "del-zone") { this._zones.splice(+d.z, 1); return this._render(); }
      if (act === "add-section") {
        this._zones[+d.z].sections.push({ id: genId(), name: "Porțiune", area: 0 });
        return this._render();
      }
      if (act === "del-section") {
        const z = this._zones[+d.z];
        const sid = z.sections[+d.s].id;
        z.sections.splice(+d.s, 1);
        (z.groups || []).forEach((g) => { if (g.rates) delete g.rates[sid]; });
        return this._render();
      }
      if (act === "add-group") {
        this._zones[+d.z].groups.push({ id: genId(), name: "Grup", switches: [], rates: {} });
        return this._render();
      }
      if (act === "del-group") { this._zones[+d.z].groups.splice(+d.g, 1); return this._render(); }

      if (act === "save-zones") {
        await this._ws({ type: "zoneflow/save_zones", zones: this._zones });
        this._toast("Zonele au fost salvate.");
        return this._reload(true);
      }
      if (act === "save-general") {
        const weather = this.shadowRoot.getElementById("weather").value;
        const testmin = parseFloat(this.shadowRoot.getElementById("testmin").value) || 10;
        const fdays = parseInt(this.shadowRoot.getElementById("fdays").value) || 7;
        await this._ws({ type: "zoneflow/save_general", weather_entity: weather, test_minutes: testmin, forecast_days: fdays });
        // ora + factor (entități)
        const c = this._data.controls || {};
        const t = this.shadowRoot.getElementById("starttime").value;
        if (c.start_time && t) await this._hass.callService("time", "set_value", { entity_id: c.start_time, time: t.length === 5 ? t + ":00" : t });
        const f = this.shadowRoot.getElementById("factor").value;
        if (c.factor && f !== "") await this._hass.callService("number", "set_value", { entity_id: c.factor, value: parseFloat(f) });
        const iv = this.shadowRoot.getElementById("interval").value;
        if (c.interval && iv !== "") await this._hass.callService("number", "set_value", { entity_id: c.interval, value: parseInt(iv) });
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
  ul.help{line-height:1.5;} ul.help li{margin-bottom:6px;}
  p.muted{line-height:1.5;}
`;

customElements.define("zoneflow-panel", ZoneFlowPanel);
