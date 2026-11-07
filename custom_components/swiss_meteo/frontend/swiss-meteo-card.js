/*
 * Swiss Meteo card for Home Assistant.
 *
 * The MeteoSwiss forecast of a place as one card: the current conditions
 * (station values when a station is configured), an hourly chart with the
 * temperature line, its uncertainty band, precipitation bars with their
 * 10-90 % range and the symbols, and the nine-day strip. Everything comes
 * from the integration's weather entity and its forecast subscriptions.
 *
 * Icons: Meteocons by Bas Milius (MIT), bundled under /swiss_meteo_files/icons/.
 * Served by the integration at /swiss_meteo_files/swiss-meteo-card.js.
 */

const CARD_VERSION = "0.1.0";
const ICON_BASE = "/swiss_meteo_files/icons/";

const LABELS = {
  humidity: { de: "Feuchte", en: "Humidity", fr: "Humidité", it: "Umidità" },
  wind: { de: "Wind", en: "Wind", fr: "Vent", it: "Vento" },
  gust: { de: "Böen", en: "Gusts", fr: "Rafales", it: "Raffiche" },
  pressure: { de: "Druck", en: "Pressure", fr: "Pression", it: "Pressione" },
  dew_point: { de: "Taupunkt", en: "Dew point", fr: "Point de rosée", it: "Punto di rugiada" },
  rain_prob: { de: "Regenwahrsch.", en: "Rain chance", fr: "Prob. de pluie", it: "Prob. pioggia" },
  zero_degree: { de: "Nullgradgrenze", en: "Zero-degree level", fr: "Isotherme 0 °C", it: "Isoterma 0 °C" },
  station: { de: "Station", en: "Station", fr: "Station", it: "Stazione" },
  forecast: { de: "Prognose", en: "Forecast", fr: "Prévision", it: "Previsione" },
  today: { de: "Heute", en: "Today", fr: "Aujourd'hui", it: "Oggi" },
  tomorrow: { de: "Morgen", en: "Tomorrow", fr: "Demain", it: "Domani" },
  source: { de: "Quelle: MeteoSchweiz, Lauf", en: "Source: MeteoSwiss, run", fr: "Source : MétéoSuisse, cycle", it: "Fonte: MeteoSvizzera, ciclo" },
  unavailable: { de: "Keine Daten", en: "No data", fr: "Pas de données", it: "Nessun dato" },
  hours: { de: "Stunden", en: "hours", fr: "heures", it: "ore" },
};

const EDITOR_LABELS = {
  entity: { de: "Wetter-Entität", en: "Weather entity", fr: "Entité météo", it: "Entità meteo" },
  title: { de: "Titel (optional)", en: "Title (optional)", fr: "Titre (facultatif)", it: "Titolo (facoltativo)" },
  hours: { de: "Stunden im Verlauf", en: "Hours in the chart", fr: "Heures dans le graphique", it: "Ore nel grafico" },
  days: { de: "Tage", en: "Days", fr: "Jours", it: "Giorni" },
  show_current: { de: "Aktuelle Werte anzeigen", en: "Show current values", fr: "Afficher les valeurs actuelles", it: "Mostra valori attuali" },
  show_hourly: { de: "Stundenverlauf anzeigen", en: "Show hourly chart", fr: "Afficher le graphique horaire", it: "Mostra grafico orario" },
  show_daily: { de: "Tagesprognose anzeigen", en: "Show daily forecast", fr: "Afficher la prévision journalière", it: "Mostra previsione giornaliera" },
};

// MeteoSwiss symbol code -> Meteocons icon. "{dn}" becomes "day" or "night";
// the day codes 1-42 and the night codes 101-142 share one table because a
// night code has the same picture as its day counterpart, drawn at night.
const SYMBOL_ICONS = {
  1: "clear-{dn}", 2: "partly-cloudy-{dn}", 3: "partly-cloudy-{dn}", 4: "overcast-{dn}", 5: "overcast",
  6: "partly-cloudy-{dn}-rain", 7: "partly-cloudy-{dn}-sleet", 8: "partly-cloudy-{dn}-snow",
  9: "overcast-{dn}-rain", 10: "overcast-{dn}-sleet", 11: "overcast-{dn}-snow",
  12: "thunderstorms-{dn}", 13: "thunderstorms-{dn}-rain", 14: "overcast-drizzle", 15: "overcast-sleet",
  16: "overcast-snow", 17: "rain", 18: "sleet", 19: "snow", 20: "extreme-rain", 21: "sleet", 22: "extreme-snow",
  23: "thunderstorms-rain", 24: "thunderstorms-rain", 25: "thunderstorms-extreme-rain", 26: "partly-cloudy-{dn}",
  27: "overcast", 28: "fog-{dn}", 29: "partly-cloudy-{dn}-rain", 30: "partly-cloudy-{dn}-snow",
  31: "partly-cloudy-{dn}-sleet", 32: "thunderstorms-{dn}-rain", 33: "overcast-{dn}-rain", 34: "overcast-{dn}-snow",
  35: "overcast", 36: "thunderstorms-{dn}", 37: "thunderstorms-{dn}-snow", 38: "thunderstorms-rain",
  39: "thunderstorms-snow", 40: "thunderstorms", 41: "thunderstorms", 42: "thunderstorms-snow",
};
const CONDITION_ICONS = {
  "clear-night": "clear-night", sunny: "clear-day", partlycloudy: "partly-cloudy-{dn}", cloudy: "overcast",
  fog: "fog-{dn}", rainy: "rain", pouring: "extreme-rain", snowy: "snow", "snowy-rainy": "sleet",
  lightning: "thunderstorms-{dn}", "lightning-rainy": "thunderstorms-{dn}-rain", hail: "hail", windy: "wind",
  "windy-variant": "wind", exceptional: "not-available",
};

function lang(hass) {
  return ((hass && hass.language) || "en").split("-")[0];
}
function L(hass, key) {
  const l = lang(hass);
  return (LABELS[key] && (LABELS[key][l] || LABELS[key].en)) || key;
}
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function iconFor(symbol, condition, night) {
  const dn = night ? "night" : "day";
  let name = null;
  if (symbol != null) {
    const code = Number(symbol);
    name = SYMBOL_ICONS[code > 100 ? code - 100 : code];
    if (code > 100) night = true;
  }
  if (!name) name = CONDITION_ICONS[condition] || "not-available";
  return ICON_BASE + name.replace("{dn}", symbol != null && Number(symbol) > 100 ? "night" : dn) + ".svg";
}
function fmt(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "–";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function bearingArrow(deg) {
  if (deg == null) return "";
  return `<span class="arrow" style="transform: rotate(${Number(deg) + 180}deg)">➤</span>`;
}
function weekday(date, l) {
  return date.toLocaleDateString(l, { weekday: "short" });
}
function isNightAt(date, hass) {
  const sun = hass.states["sun.sun"];
  if (!sun) return date.getHours() < 7 || date.getHours() >= 19;
  const rising = sun.attributes.next_rising ? new Date(sun.attributes.next_rising) : null;
  const setting = sun.attributes.next_setting ? new Date(sun.attributes.next_setting) : null;
  if (!rising || !setting) return false;
  // Approximate: use today's rise/set hours for any day.
  const h = date.getHours() + date.getMinutes() / 60;
  const riseH = rising.getHours() + rising.getMinutes() / 60;
  const setH = setting.getHours() + setting.getMinutes() / 60;
  return h < riseH || h >= setH;
}

class SwissMeteoCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hourly = null;
    this._daily = null;
    this._unsubs = [];
    this._lastState = null;
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = {
      hours: 24,
      days: 9,
      show_current: true,
      show_hourly: true,
      show_daily: true,
      ...config,
    };
    this._subscribed = false;
    this._render();
  }

  static getConfigElement() {
    return document.createElement("swiss-meteo-card-editor");
  }

  static getStubConfig(hass, entities) {
    const entity = (entities || []).find((e) => e.startsWith("weather.swiss_meteo")) || (entities || []).find((e) => e.startsWith("weather.")) || "";
    return { entity, hours: 24, days: 9 };
  }

  getCardSize() {
    let size = 1;
    if (this._config.show_current) size += 2;
    if (this._config.show_hourly) size += 3;
    if (this._config.show_daily) size += 2;
    return size;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._subscribed && hass.connection && this._config) this._subscribe();
    const state = hass.states[this._config.entity];
    const stamp = state ? state.last_updated + "|" + JSON.stringify(state.attributes).length : "none";
    if (stamp !== this._lastState) {
      this._lastState = stamp;
      this._render();
    }
  }

  connectedCallback() {
    if (this._hass && !this._subscribed) this._subscribe();
  }

  disconnectedCallback() {
    this._unsubscribe();
  }

  _subscribe() {
    this._unsubscribe();
    this._subscribed = true;
    const entity = this._config.entity;
    const features = this._hass.states[entity]?.attributes?.supported_features || 0;
    const types = [];
    if (features & 2) types.push("daily");
    if (features & 1) types.push("hourly");
    for (const type of types) {
      try {
        const p = this._hass.connection.subscribeMessage(
          (msg) => {
            if (type === "daily") this._daily = msg.forecast || [];
            else this._hourly = msg.forecast || [];
            this._render();
          },
          { type: "weather/subscribe_forecast", forecast_type: type, entity_id: entity }
        );
        this._unsubs.push(p);
      } catch (e) {
        // older frontends: no forecast subscription
      }
    }
  }

  _unsubscribe() {
    for (const p of this._unsubs) Promise.resolve(p).then((u) => typeof u === "function" && u()).catch(() => {});
    this._unsubs = [];
    this._subscribed = false;
  }

  _render() {
    if (!this._hass || !this._config) return;
    const hass = this._hass;
    const state = hass.states[this._config.entity];
    const title = this._config.title || (state ? state.attributes.friendly_name : this._config.entity);
    if (!state || state.state === "unavailable") {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card><div class="head"><div class="title">${esc(title)}</div></div><div class="empty">${esc(L(hass, "unavailable"))}</div></ha-card>`;
      return;
    }
    const parts = [this._style(), "<ha-card>"];
    parts.push(`<div class="head"><div class="title">${esc(title)}</div></div>`);
    if (this._config.show_current) parts.push(this._renderCurrent(state));
    if (this._config.show_hourly && this._hourly && this._hourly.length) parts.push(this._renderHourly());
    if (this._config.show_daily && this._daily && this._daily.length) parts.push(this._renderDaily());
    const run = state.attributes.forecast_run ? new Date(state.attributes.forecast_run) : null;
    parts.push(`<div class="foot">${esc(L(hass, "source"))} ${run ? esc(run.toLocaleString(lang(hass), { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })) : ""}</div>`);
    parts.push("</ha-card>");
    this.shadowRoot.innerHTML = parts.join("");
    this.shadowRoot.querySelector(".head")?.addEventListener("click", () => this._more(state.entity_id));
  }

  _more(entityId) {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }

  _renderCurrent(state) {
    const hass = this._hass;
    const a = state.attributes;
    const night = isNightAt(new Date(), hass);
    const icon = iconFor(a.symbol, state.state, night);
    const conditionText = hass.localize ? hass.localize(`component.weather.entity_component._.state.${state.state}`) || state.state : state.state;
    const chips = [];
    if (a.humidity != null) chips.push([L(hass, "humidity"), `${fmt(a.humidity)} %`, "humidity"]);
    if (a.wind_speed != null) chips.push([L(hass, "wind"), `${fmt(a.wind_speed)} ${esc(a.wind_speed_unit || "km/h")} ${bearingArrow(a.wind_bearing)}`, "wind"]);
    if (a.wind_gust_speed != null) chips.push([L(hass, "gust"), `${fmt(a.wind_gust_speed)} ${esc(a.wind_speed_unit || "km/h")}`, "windsock"]);
    if (a.pressure != null) chips.push([L(hass, "pressure"), `${fmt(a.pressure)} ${esc(a.pressure_unit || "hPa")}`, "barometer"]);
    if (a.dew_point != null) chips.push([L(hass, "dew_point"), `${fmt(a.dew_point, 1)} °`, "thermometer"]);
    if (a.precipitation_probability != null) chips.push([L(hass, "rain_prob"), `${fmt(a.precipitation_probability)} %`, "umbrella"]);
    if (a.zero_degree_level != null) chips.push([L(hass, "zero_degree"), `${fmt(a.zero_degree_level)} m`, "snowflake"]);
    const station = a.station ? `<div class="station">${esc(L(hass, "station"))} ${esc(a.station)}${a.station_time ? " · " + esc(new Date(a.station_time).toLocaleTimeString(lang(hass), { hour: "2-digit", minute: "2-digit" })) : ""}</div>` : "";
    return `<div class="current">
      <img class="big" src="${icon}" alt="${esc(state.state)}" />
      <div class="now">
        <div class="temp">${fmt(a.temperature, 1)}<span class="unit">${esc(a.temperature_unit || "°C")}</span></div>
        <div class="cond">${esc(conditionText)}</div>
        ${station}
      </div>
      <div class="chips">${chips.map(([k, v, ic]) => `<div class="chip"><img src="${ICON_BASE}${ic}.svg" alt="" /><div><div class="k">${esc(k)}</div><div class="v">${v}</div></div></div>`).join("")}</div>
    </div>`;
  }

  _renderHourly() {
    const hass = this._hass;
    const rows = this._hourly.slice(0, Math.max(6, Math.min(72, Number(this._config.hours) || 24)));
    const n = rows.length;
    const W = 1000, H = 260, padL = 36, padR = 36, padT = 70, padB = 44;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const x = (i) => padL + (i + 0.5) * (plotW / n);
    const temps = rows.map((r) => r.temperature).filter((v) => v != null);
    const tmin = Math.min(...temps, ...rows.map((r) => r.temperature_min ?? Infinity));
    const tmax = Math.max(...temps, ...rows.map((r) => r.temperature_max ?? -Infinity));
    const lo = Math.floor(tmin - 1), hi = Math.ceil(tmax + 1);
    const y = (t) => padT + plotH - ((t - lo) / Math.max(1, hi - lo)) * plotH;
    const pmax = Math.max(1, ...rows.map((r) => Math.max(r.precipitation || 0, r.precipitation_max || 0)));
    const barH = (p) => ((p || 0) / pmax) * (plotH * 0.55);
    const l = lang(hass);
    const parts = [];
    // precipitation bars with range whiskers
    rows.forEach((r, i) => {
      const bw = (plotW / n) * 0.6;
      const p = r.precipitation || 0;
      const prob = r.precipitation_probability != null ? Math.max(0.15, r.precipitation_probability / 100) : 0.8;
      if (p > 0 || (r.precipitation_max || 0) > 0) {
        parts.push(`<rect class="bar" x="${x(i) - bw / 2}" y="${padT + plotH - barH(p)}" width="${bw}" height="${barH(p)}" opacity="${prob.toFixed(2)}"><title>${esc(fmt(p, 1))} mm</title></rect>`);
        if (r.precipitation_max != null && r.precipitation_max > p) {
          parts.push(`<line class="whisker" x1="${x(i)}" x2="${x(i)}" y1="${padT + plotH - barH(r.precipitation_max)}" y2="${padT + plotH - barH(r.precipitation_min || 0)}" />`);
        }
      }
    });
    // temperature band
    if (rows.some((r) => r.temperature_min != null && r.temperature_max != null)) {
      const top = rows.map((r, i) => `${x(i)},${y(r.temperature_max ?? r.temperature)}`).join(" ");
      const bottom = rows.slice().reverse().map((r, i) => `${x(n - 1 - i)},${y(r.temperature_min ?? r.temperature)}`).join(" ");
      parts.push(`<polygon class="band" points="${top} ${bottom}" />`);
    }
    // temperature line
    const line = rows.map((r, i) => (r.temperature != null ? `${x(i)},${y(r.temperature)}` : null)).filter(Boolean).join(" ");
    parts.push(`<polyline class="line" points="${line}" />`);
    // zero line
    if (lo < 0 && hi > 0) parts.push(`<line class="zero" x1="${padL}" x2="${W - padR}" y1="${y(0)}" y2="${y(0)}" />`);
    // labels: temperature every 3 h, icons every 3 h, time axis
    rows.forEach((r, i) => {
      const d = new Date(r.datetime);
      const step = n > 36 ? 6 : 3;
      if (i % step === 0) {
        if (r.temperature != null) parts.push(`<text class="tlabel" x="${x(i)}" y="${y(r.temperature) - 10}">${fmt(r.temperature)}°</text>`);
        const icon = iconFor(r.symbol, r.condition, isNightAt(d, hass));
        parts.push(`<image href="${icon}" x="${x(i) - 22}" y="${padT - 62}" width="44" height="44" />`);
        parts.push(`<text class="xlabel" x="${x(i)}" y="${H - 22}">${esc(d.toLocaleTimeString(l, { hour: "2-digit", minute: "2-digit" }))}</text>`);
        if (d.getHours() < step) parts.push(`<text class="dlabel" x="${x(i)}" y="${H - 6}">${esc(weekday(d, l))}</text>`);
      }
      if (d.getHours() === 0 && i > 0) parts.push(`<line class="day" x1="${x(i) - plotW / n / 2}" x2="${x(i) - plotW / n / 2}" y1="${padT - 10}" y2="${padT + plotH}" />`);
    });
    // precipitation scale on the right
    parts.push(`<text class="plabel" x="${W - padR + 6}" y="${padT + plotH - barH(pmax) + 4}">${fmt(pmax, pmax < 2 ? 1 : 0)} mm</text>`);
    return `<div class="hourly"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${parts.join("")}</svg></div>`;
  }

  _renderDaily() {
    const hass = this._hass;
    const l = lang(hass);
    const today = new Date();
    const rows = this._daily.slice(0, Math.max(1, Math.min(9, Number(this._config.days) || 9)));
    const cells = rows.map((r, i) => {
      const d = new Date(r.datetime);
      const label = i === 0 && d.toDateString() === today.toDateString() ? L(hass, "today") : weekday(d, l);
      const icon = iconFor(r.symbol, r.condition, false);
      const prob = r.precipitation_probability != null ? `<div class="prob">${fmt(r.precipitation_probability)} %</div>` : "";
      const rain = r.precipitation != null ? `<div class="rain ${r.precipitation > 0 ? "" : "dry"}">${fmt(r.precipitation, r.precipitation < 10 ? 1 : 0)} mm</div>` : "";
      const range = r.precipitation_max != null && r.precipitation_max > 0 ? `<div class="range">${fmt(r.precipitation_min || 0, 0)}–${fmt(r.precipitation_max, 0)}</div>` : "";
      return `<div class="day"><div class="wd">${esc(label)}</div><img src="${icon}" alt="${esc(r.condition || "")}" /><div class="hi">${fmt(r.temperature)}°</div><div class="lo">${fmt(r.templow)}°</div>${rain}${prob}${range}</div>`;
    });
    return `<div class="daily">${cells.join("")}</div>`;
  }

  _style() {
    return `<style>
      :host { display: block; }
      ha-card { padding: 12px 16px 8px; overflow: hidden; }
      .head { display: flex; align-items: baseline; justify-content: space-between; cursor: pointer; }
      .title { font-size: 1.15em; font-weight: 500; }
      .empty { opacity: 0.7; padding: 16px 0; }
      .current { display: grid; grid-template-columns: 112px 1fr; grid-template-areas: "icon now" "chips chips"; gap: 4px 12px; align-items: center; margin-top: 4px; }
      .current .big { grid-area: icon; width: 112px; height: 112px; }
      .current .now { grid-area: now; }
      .temp { font-size: 3em; font-weight: 300; line-height: 1; }
      .temp .unit { font-size: 0.4em; margin-left: 2px; vertical-align: top; }
      .cond { font-size: 1.05em; margin-top: 4px; text-transform: capitalize; }
      .station { font-size: 0.8em; opacity: 0.65; margin-top: 2px; }
      .chips { grid-area: chips; display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 4px; }
      .chip { display: flex; align-items: center; gap: 4px; min-width: 110px; }
      .chip img { width: 34px; height: 34px; }
      .chip .k { font-size: 0.7em; opacity: 0.65; }
      .chip .v { font-size: 0.95em; }
      .arrow { display: inline-block; font-size: 0.8em; opacity: 0.8; }
      .hourly { margin-top: 8px; }
      .hourly svg { width: 100%; height: auto; display: block; font-family: inherit; }
      .bar { fill: var(--swiss-meteo-rain, #4a90d9); }
      .whisker { stroke: var(--swiss-meteo-rain, #4a90d9); stroke-width: 2; opacity: 0.5; stroke-dasharray: 4 3; }
      .band { fill: var(--swiss-meteo-temp, #e07a2d); opacity: 0.15; }
      .line { fill: none; stroke: var(--swiss-meteo-temp, #e07a2d); stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
      .zero { stroke: var(--secondary-text-color, #888); stroke-width: 1; stroke-dasharray: 6 4; opacity: 0.6; }
      .day { stroke: var(--divider-color, #666); stroke-width: 1; opacity: 0.5; }
      .tlabel { font-size: 20px; text-anchor: middle; fill: var(--primary-text-color); }
      .xlabel { font-size: 19px; text-anchor: middle; fill: var(--secondary-text-color); }
      .dlabel { font-size: 18px; text-anchor: middle; fill: var(--primary-text-color); font-weight: 500; }
      .plabel { font-size: 17px; fill: var(--swiss-meteo-rain, #4a90d9); }
      .daily { display: flex; gap: 2px; margin-top: 10px; overflow-x: auto; }
      .daily .day { flex: 1 1 0; min-width: 58px; text-align: center; padding: 4px 0; border-radius: 8px; stroke: none; opacity: 1; }
      .daily .day:first-child { background: var(--secondary-background-color, rgba(128,128,128,0.08)); }
      .daily img { width: 48px; height: 48px; }
      .daily .wd { font-size: 0.8em; opacity: 0.75; }
      .daily .hi { font-weight: 500; }
      .daily .lo { opacity: 0.6; font-size: 0.9em; }
      .daily .rain { font-size: 0.8em; color: var(--swiss-meteo-rain, #4a90d9); }
      .daily .rain.dry { opacity: 0.45; color: inherit; }
      .daily .prob { font-size: 0.72em; opacity: 0.7; }
      .daily .range { font-size: 0.68em; opacity: 0.55; }
      .foot { font-size: 0.72em; opacity: 0.55; margin-top: 8px; text-align: right; }
    </style>`;
  }
}

customElements.define("swiss-meteo-card", SwissMeteoCard);

class SwissMeteoCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { hours: 24, days: 9, show_current: true, show_hourly: true, show_daily: true, ...config };
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    this._render();
  }
  _label(key) {
    const l = lang(this._hass);
    return (EDITOR_LABELS[key] && (EDITOR_LABELS[key][l] || EDITOR_LABELS[key].en)) || key;
  }
  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        this._config = { ...this._config, ...ev.detail.value };
        const event = new Event("config-changed", { bubbles: true, composed: true });
        event.detail = { config: this._config };
        this.dispatchEvent(event);
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = this._config;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "weather" } } },
      { name: "title", selector: { text: {} } },
      { name: "hours", selector: { select: { mode: "dropdown", options: ["12", "24", "36", "48", "72"].map((v) => ({ value: Number(v), label: v })) } } },
      { name: "days", selector: { number: { min: 1, max: 9, mode: "box" } } },
      { name: "show_current", selector: { boolean: {} } },
      { name: "show_hourly", selector: { boolean: {} } },
      { name: "show_daily", selector: { boolean: {} } },
    ];
    this._form.computeLabel = (s) => this._label(s.name);
  }
}

customElements.define("swiss-meteo-card-editor", SwissMeteoCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "swiss-meteo-card",
  name: "Swiss Meteo",
  description: "MeteoSwiss forecast: current values, hourly chart with uncertainty, nine-day strip.",
  preview: true,
});

console.info(`%c SWISS-METEO-CARD %c ${CARD_VERSION} `, "color: white; background: #c8102e; font-weight: 700;", "color: #c8102e; background: white; font-weight: 700;");
