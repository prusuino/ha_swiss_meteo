/*
 * Swiss Meteo card for Home Assistant.
 *
 * The MeteoSwiss forecast of a place as one card: the current conditions
 * (station values when a station is configured), an hourly chart with the
 * temperature line, its uncertainty band, precipitation bars with their
 * 10-90 % range and the symbols, and the nine-day strip. Everything comes
 * from the integration's weather entity and its forecast subscriptions.
 *
 * Three more cards share this file: swiss-meteo-forecast-card (the drop-in
 * for the weather-forecast card), swiss-meteo-daily-card (the nine-day list
 * in the look of the MeteoSwiss local forecast page) and swiss-meteo-map-card
 * (Switzerland with a pill per configured place). The outline and the lakes
 * of the map are from Natural Earth (public domain).
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
  pollen: { de: "Pollen", en: "Pollen", fr: "Pollens", it: "Pollini" },
  level_none: { de: "keine", en: "none", fr: "aucun", it: "nessuno" },
  level_low: { de: "schwach", en: "low", fr: "faible", it: "debole" },
  level_moderate: { de: "mässig", en: "moderate", fr: "modéré", it: "moderato" },
  level_high: { de: "stark", en: "high", fr: "fort", it: "forte" },
  level_very_high: { de: "sehr stark", en: "very high", fr: "très fort", it: "molto forte" },
  birch: { de: "Birke", en: "birch", fr: "bouleau", it: "betulla" },
  grasses: { de: "Gräser", en: "grasses", fr: "graminées", it: "graminacee" },
  alder: { de: "Erle", en: "alder", fr: "aulne", it: "ontano" },
  hazel: { de: "Hasel", en: "hazel", fr: "noisetier", it: "nocciolo" },
  beech: { de: "Buche", en: "beech", fr: "hêtre", it: "faggio" },
  ash: { de: "Esche", en: "ash", fr: "frêne", it: "frassino" },
  oak: { de: "Eiche", en: "oak", fr: "chêne", it: "quercia" },
};

const EDITOR_LABELS = {
  entity: { de: "Wetter-Entität", en: "Weather entity", fr: "Entité météo", it: "Entità meteo" },
  title: { de: "Titel (optional)", en: "Title (optional)", fr: "Titre (facultatif)", it: "Titolo (facoltativo)" },
  hours: { de: "Stunden im Verlauf", en: "Hours in the chart", fr: "Heures dans le graphique", it: "Ore nel grafico" },
  days: { de: "Tage", en: "Days", fr: "Jours", it: "Giorni" },
  show_current: { de: "Aktuelle Werte anzeigen", en: "Show current values", fr: "Afficher les valeurs actuelles", it: "Mostra valori attuali" },
  show_hourly: { de: "Stundenverlauf anzeigen", en: "Show hourly chart", fr: "Afficher le graphique horaire", it: "Mostra grafico orario" },
  show_daily: { de: "Tagesprognose anzeigen", en: "Show daily forecast", fr: "Afficher la prévision journalière", it: "Mostra previsione giornaliera" },
  theme: { de: "Farbwelt", en: "Colour scheme", fr: "Palette", it: "Palette" },
  animated: { de: "Animierte Symbole", en: "Animated icons", fr: "Icônes animées", it: "Icone animate" },
  size: { de: "Grösse (Symbole und Schrift)", en: "Size (icons and text)", fr: "Taille (icônes et texte)", it: "Dimensione (icone e testo)" },
  show_pollen: { de: "Pollen anzeigen", en: "Show pollen", fr: "Afficher les pollens", it: "Mostra pollini" },
  pollen_entity: { de: "Pollen-Sensor (optional, sonst der des Eintrags)", en: "Pollen sensor (optional, else the entry's own)", fr: "Capteur de pollens (facultatif, sinon celui de l'entrée)", it: "Sensore pollini (facoltativo, altrimenti quello della voce)" },
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

const ASL = { de: "m ü. M.", en: "m a.s.l.", fr: "m s. m.", it: "m s.l.m." };

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
function iconUrl(name, animated = true) {
  return ICON_BASE + (animated === false ? "static/" : "") + name + ".svg";
}
function iconFor(symbol, condition, night, animated = true) {
  const dn = night ? "night" : "day";
  let name = null;
  if (symbol != null) {
    const code = Number(symbol);
    name = SYMBOL_ICONS[code > 100 ? code - 100 : code];
    if (code > 100) night = true;
  }
  if (!name) name = CONDITION_ICONS[condition] || "not-available";
  return iconUrl(name.replace("{dn}", symbol != null && Number(symbol) > 100 ? "night" : dn), animated);
}
function fmt(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return "–";
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
// The entry's pollen-level sensor: configured, or derived from the weather
// entity id (weather.swiss_meteo_<id> -> sensor.swiss_meteo_<id>_pollen_level).
function pollenEntity(hass, config) {
  if (config.pollen_entity) return config.pollen_entity;
  const m = /^weather\.(.+)$/.exec(config.entity || "");
  const id = m ? `sensor.${m[1]}_pollen_level` : null;
  return id && hass.states[id] ? id : null;
}
const TREE_POLLEN = new Set(["birch", "alder", "hazel", "beech", "ash", "oak"]);
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
      show_pollen: true,
      animated: true,
      theme: "meteo",
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
    const pollen = this._config.show_pollen ? hass.states[pollenEntity(hass, this._config) || ""] : null;
    const stamp = (state ? state.last_updated + "|" + JSON.stringify(state.attributes).length : "none") + (pollen ? "|" + pollen.last_updated : "");
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
    const a = state ? state.attributes : {};
    let title = this._config.title;
    if (!title) {
      title = a.point_name || a.friendly_name || this._config.entity;
      if (a.point_name && a.elevation != null) title += `, ${fmt(a.elevation)} ${ASL[lang(hass)] || ASL.en}`;
    }
    const cls = this._config.theme === "ha" ? "" : "meteo";
    if (!state || state.state === "unavailable") {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card class="${cls}"><div class="head"><div class="title">${esc(title)}</div></div><div class="empty">${esc(L(hass, "unavailable"))}</div></ha-card>`;
      return;
    }
    const parts = [this._style(), `<ha-card class="${cls}">`];
    parts.push(`<div class="head"><div class="title">${esc(title)}</div></div>`);
    if (this._config.show_current) parts.push(this._renderCurrent(state));
    if (this._config.show_hourly && this._hourly && this._hourly.length) parts.push(this._renderHourly());
    if (this._config.show_daily && this._daily && this._daily.length) parts.push(this._renderDaily());
    const run = state.attributes.forecast_run ? new Date(state.attributes.forecast_run) : null;
    parts.push(`<div class="foot">${esc(L(hass, "source"))} ${run ? esc(run.toLocaleString(lang(hass), { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })) : ""}</div>`);
    parts.push("</ha-card>");
    this.shadowRoot.innerHTML = parts.join("");
    this.shadowRoot.querySelector(".head")?.addEventListener("click", () => this._more(state.entity_id));
    for (const el of this.shadowRoot.querySelectorAll(".chip.link")) el.addEventListener("click", () => this._more(el.dataset.entity));
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
    const icon = iconFor(a.symbol, state.state, night, this._config.animated);
    const conditionText = hass.localize ? hass.localize(`component.weather.entity_component._.state.${state.state}`) || state.state : state.state;
    const chips = [];
    if (a.humidity != null) chips.push([L(hass, "humidity"), `${fmt(a.humidity)} %`, "humidity"]);
    if (a.wind_speed != null) chips.push([L(hass, "wind"), `${fmt(a.wind_speed)} ${esc(a.wind_speed_unit || "km/h")} ${bearingArrow(a.wind_bearing)}`, "wind"]);
    if (a.wind_gust_speed != null) chips.push([L(hass, "gust"), `${fmt(a.wind_gust_speed)} ${esc(a.wind_speed_unit || "km/h")}`, "windsock"]);
    if (a.pressure != null) chips.push([L(hass, "pressure"), `${fmt(a.pressure)} ${esc(a.pressure_unit || "hPa")}`, "barometer"]);
    if (a.dew_point != null) chips.push([L(hass, "dew_point"), `${fmt(a.dew_point, 1)} °`, "thermometer"]);
    if (a.precipitation_probability != null) chips.push([L(hass, "rain_prob"), `${fmt(a.precipitation_probability)} %`, "umbrella"]);
    if (a.zero_degree_level != null) chips.push([L(hass, "zero_degree"), `${fmt(a.zero_degree_level)} m`, "snowflake"]);
    const pollenId = this._config.show_pollen ? pollenEntity(hass, this._config) : null;
    const pollen = pollenId ? hass.states[pollenId] : null;
    if (pollen && pollen.state && pollen.state !== "unavailable" && pollen.state !== "unknown") {
      const level = pollen.state;
      const levelText = (hass.localize && hass.localize(`component.swiss_meteo.entity.sensor.pollen_level.state.${level}`)) || L(hass, `level_${level}`);
      const highest = Array.isArray(pollen.attributes.highest) ? pollen.attributes.highest : [];
      const species = level === "none" ? "" : highest.map((s) => L(hass, s)).join(", ");
      const icon = level === "none" || !highest.length ? "pollen" : highest.every((s) => TREE_POLLEN.has(s)) ? "pollen-tree" : "pollen-grass";
      chips.push([L(hass, "pollen"), `${esc(levelText)}${species ? ` <span class="sub">${esc(species)}</span>` : ""}`, icon, pollenId]);
    }
    const station = a.station ? `<div class="station">${esc(L(hass, "station"))} ${esc(a.station)}${a.station_time ? " · " + esc(new Date(a.station_time).toLocaleTimeString(lang(hass), { hour: "2-digit", minute: "2-digit" })) : ""}</div>` : "";
    return `<div class="current">
      <img class="big" src="${icon}" alt="${esc(state.state)}" />
      <div class="now">
        <div class="temp">${fmt(a.temperature, 1)}<span class="unit">${esc(a.temperature_unit || "°C")}</span></div>
        <div class="cond">${esc(conditionText)}</div>
        ${station}
      </div>
      <div class="chips">${chips.map(([k, v, ic, id]) => `<div class="chip${id ? " link" : ""}"${id ? ` data-entity="${esc(id)}"` : ""}><img src="${iconUrl(ic, this._config.animated)}" alt="" /><div><div class="k">${esc(k)}</div><div class="v">${v}</div></div></div>`).join("")}</div>
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
        const icon = iconFor(r.symbol, r.condition, isNightAt(d, hass), this._config.animated);
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
      const icon = iconFor(r.symbol, r.condition, false, this._config.animated);
      const prob = r.precipitation_probability != null ? `<div class="prob">${fmt(r.precipitation_probability)} %</div>` : "";
      const rain = r.precipitation != null ? `<div class="rain ${r.precipitation > 0 ? "" : "dry"}">${fmt(r.precipitation, r.precipitation < 10 ? 1 : 0)} mm</div>` : "";
      const range = r.precipitation_max != null && r.precipitation_max > 0 ? `<div class="range">${fmt(r.precipitation_min || 0, 0)}–${fmt(r.precipitation_max, 0)}</div>` : "";
      return `<div class="day"><div class="wd">${esc(label)}</div><img src="${icon}" alt="${esc(r.condition || "")}" /><div class="tt"><div class="lo">${fmt(r.templow)}°</div><div class="hi">${fmt(r.temperature)}°</div></div>${rain}${prob}${range}</div>`;
    });
    return `<div class="daily">${cells.join("")}</div>`;
  }

  _style() {
    return `<style>
      :host { display: block; }
      ha-card { padding: 12px 16px 8px; overflow: hidden;
        --sm-text: var(--primary-text-color); --sm-dim: var(--secondary-text-color); --sm-panel: var(--secondary-background-color, rgba(128,128,128,0.08));
        --sm-box: rgba(128,128,128,0.18); --sm-line: var(--divider-color, #666); --sm-temp: var(--swiss-meteo-temp, #e07a2d); --sm-rain: var(--swiss-meteo-rain, #4a90d9); }
      ha-card.meteo { background: #1c2733; color: #fff; padding: 16px 16px 10px;
        --sm-text: #fff; --sm-dim: #c3ccd6; --sm-panel: #2b3a4b; --sm-box: #4a5f75; --sm-line: #1c2733; --sm-temp: #ff4d3d; --sm-rain: #5fb0f0; }
      .head { display: flex; align-items: baseline; justify-content: space-between; cursor: pointer; }
      .title { font-size: 1.15em; font-weight: 500; }
      ha-card.meteo .title { font-size: 1.6em; font-weight: 700; line-height: 1.15; }
      .empty { opacity: 0.7; padding: 16px 0; }
      .current { display: grid; grid-template-columns: 112px 1fr; grid-template-areas: "icon now" "chips chips"; gap: 4px 12px; align-items: center; margin-top: 4px; }
      .current .big { grid-area: icon; width: 112px; height: 112px; }
      .current .now { grid-area: now; }
      .temp { font-size: 3em; font-weight: 300; line-height: 1; }
      .temp .unit { font-size: 0.4em; margin-left: 2px; vertical-align: top; }
      .cond { font-size: 1.05em; margin-top: 4px; text-transform: capitalize; }
      .station { font-size: 0.8em; opacity: 0.65; margin-top: 2px; }
      .chips { grid-area: chips; display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 4px; }
      ha-card.meteo .chips { background: var(--sm-panel); border-radius: 4px; padding: 8px 12px; margin-top: 10px; gap: 6px 14px; }
      .chip { display: flex; align-items: center; gap: 4px; min-width: 110px; }
      .chip img { width: 34px; height: 34px; }
      .chip .k { font-size: 0.7em; opacity: 0.65; }
      .chip .v { font-size: 0.95em; }
      .chip.link { cursor: pointer; }
      .chip .sub { font-size: 0.8em; opacity: 0.7; }
      .arrow { display: inline-block; font-size: 0.8em; opacity: 0.8; }
      .hourly { margin-top: 8px; }
      .hourly svg { width: 100%; height: auto; display: block; font-family: inherit; }
      ha-card.meteo .hourly { background: var(--sm-panel); border-radius: 4px; padding: 6px 4px 2px; margin-top: 12px; }
      .bar { fill: var(--sm-rain); }
      .whisker { stroke: var(--sm-rain); stroke-width: 2; opacity: 0.5; stroke-dasharray: 4 3; }
      .band { fill: var(--sm-temp); opacity: 0.15; }
      ha-card.meteo .band { opacity: 0.22; }
      .line { fill: none; stroke: var(--sm-temp); stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
      .zero { stroke: var(--sm-dim); stroke-width: 1; stroke-dasharray: 6 4; opacity: 0.6; }
      .day { stroke: var(--sm-line); stroke-width: 1; opacity: 0.5; }
      ha-card.meteo .day { stroke: #fff; opacity: 0.25; }
      .tlabel { font-size: 20px; text-anchor: middle; fill: var(--sm-text); }
      .xlabel { font-size: 19px; text-anchor: middle; fill: var(--sm-dim); }
      .dlabel { font-size: 18px; text-anchor: middle; fill: var(--sm-text); font-weight: 500; }
      .plabel { font-size: 17px; fill: var(--sm-rain); }
      .daily { display: flex; gap: 2px; margin-top: 10px; overflow-x: auto; }
      ha-card.meteo .daily { background: var(--sm-panel); border-radius: 4px; padding: 8px 4px; gap: 4px; }
      .daily .day { flex: 1 1 0; min-width: 58px; text-align: center; padding: 4px 0; border-radius: 8px; stroke: none; opacity: 1; }
      .daily .day:first-child { background: var(--sm-panel); }
      ha-card.meteo .daily .day:first-child { background: rgba(255,255,255,0.06); }
      .daily img { width: 48px; height: 48px; }
      .daily .wd { font-size: 0.8em; opacity: 0.75; }
      .daily .tt { display: flex; flex-direction: column; align-items: center; gap: 2px; }
      .daily .hi { font-weight: 500; }
      .daily .lo { opacity: 0.6; font-size: 0.9em; }
      ha-card.meteo .daily .tt { flex-direction: row; justify-content: center; gap: 3px; margin: 2px 0; }
      ha-card.meteo .daily .hi, ha-card.meteo .daily .lo { background: var(--sm-box); border-radius: 3px; padding: 3px 0; min-width: 2.2em; font-size: 0.9em; opacity: 1; font-weight: 400; }
      .daily .rain { font-size: 0.8em; color: var(--sm-rain); }
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
    this._config = { hours: 24, days: 9, show_current: true, show_hourly: true, show_daily: true, show_pollen: true, animated: true, theme: "meteo", ...config };
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
      { name: "show_pollen", selector: { boolean: {} } },
      { name: "pollen_entity", selector: { entity: { domain: "sensor" } } },
      { name: "animated", selector: { boolean: {} } },
      { name: "theme", selector: { select: { mode: "dropdown", options: [{ value: "meteo", label: "Swiss Meteo" }, { value: "ha", label: "Home Assistant" }] } } },
    ];
    this._form.computeLabel = (s) => this._label(s.name);
  }
}

customElements.define("swiss-meteo-card-editor", SwissMeteoCardEditor);

/* ------------------------------------------------------------------------
 * Shared pieces for the list and map cards
 * ---------------------------------------------------------------------- */

const LIST_LABELS = {
  wind: { de: "Wind", en: "Wind", fr: "Vent", it: "Vento" },
  sunshine: { de: "Sonnenschein", en: "Sunshine", fr: "Ensoleillement", it: "Soleggiamento" },
  gusts: { de: "Böen", en: "gusts", fr: "rafales", it: "raffiche" },
  asl: { de: "m ü. M.", en: "m a.s.l.", fr: "m s. m.", it: "m s.l.m." },
  today: { de: "Heute", en: "Today", fr: "Aujourd'hui", it: "Oggi" },
  tomorrow: { de: "Morgen", en: "Tomorrow", fr: "Demain", it: "Domani" },
  map_title: { de: "Wetterprognose für", en: "Weather forecast for", fr: "Prévisions météo pour", it: "Previsioni meteo per" },
  map_today: { de: "heute", en: "today", fr: "aujourd'hui", it: "oggi" },
  map_tomorrow: { de: "morgen", en: "tomorrow", fr: "demain", it: "domani" },
  no_entities: { de: "Keine Swiss-Meteo-Wetterentität gefunden", en: "No Swiss Meteo weather entity found", fr: "Aucune entité météo Swiss Meteo", it: "Nessuna entità meteo Swiss Meteo" },
  source: { de: "Quelle: MeteoSchweiz", en: "Source: MeteoSwiss", fr: "Source : MétéoSuisse", it: "Fonte: MeteoSvizzera" },
};
const LIST_EDITOR_LABELS = {
  entity: EDITOR_LABELS.entity,
  entities: { de: "Wetter-Entitäten (leer = alle Swiss Meteo)", en: "Weather entities (empty = all Swiss Meteo)", fr: "Entités météo (vide = toutes Swiss Meteo)", it: "Entità meteo (vuoto = tutte Swiss Meteo)" },
  title: EDITOR_LABELS.title,
  days: EDITOR_LABELS.days,
  day: { de: "Tag (0 = heute, 1 = morgen …)", en: "Day (0 = today, 1 = tomorrow …)", fr: "Jour (0 = aujourd'hui, 1 = demain …)", it: "Giorno (0 = oggi, 1 = domani …)" },
  show_wind: { de: "Wind einblenden", en: "Show wind", fr: "Afficher le vent", it: "Mostra vento" },
  show_sunshine: { de: "Sonnenschein einblenden", en: "Show sunshine", fr: "Afficher l'ensoleillement", it: "Mostra soleggiamento" },
  show_toggles: { de: "Schalter Wind/Sonnenschein anzeigen", en: "Show the wind/sunshine toggles", fr: "Afficher les boutons vent/soleil", it: "Mostra interruttori vento/sole" },
  show_names: { de: "Ortsnamen anzeigen", en: "Show place names", fr: "Afficher les noms", it: "Mostra nomi" },
  theme: { de: "Farbwelt", en: "Colour scheme", fr: "Palette", it: "Palette" },
  name: { de: "Name (optional)", en: "Name (optional)", fr: "Nom (facultatif)", it: "Nome (facoltativo)" },
  forecast_type: { de: "Prognose", en: "Forecast", fr: "Prévision", it: "Previsione" },
  columns: { de: "Spalten (0 = automatisch)", en: "Columns (0 = automatic)", fr: "Colonnes (0 = auto)", it: "Colonne (0 = auto)" },
  show_forecast: { de: "Prognose anzeigen", en: "Show forecast", fr: "Afficher la prévision", it: "Mostra previsione" },
  show_current: EDITOR_LABELS.show_current,
  show_details: { de: "Details (Feuchte, Wind, Niederschlag)", en: "Details (humidity, wind, precipitation)", fr: "Détails (humidité, vent, précipitations)", it: "Dettagli (umidità, vento, precipitazioni)" },
  background: { de: "Hintergrund", en: "Background", fr: "Arrière-plan", it: "Sfondo" },
  animated: EDITOR_LABELS.animated,
  size: EDITOR_LABELS.size,
};
function LL(hass, key) {
  const l = lang(hass);
  return (LIST_LABELS[key] && (LIST_LABELS[key][l] || LIST_LABELS[key].en)) || key;
}
function dayLabel(hass, date, index) {
  const l = lang(hass);
  const today = new Date();
  const tomorrow = new Date(today.getTime() + 86400000);
  if (date.toDateString() === today.toDateString()) return LL(hass, "today");
  if (date.toDateString() === tomorrow.toDateString()) return LL(hass, "tomorrow");
  return date.toLocaleDateString(l, { weekday: "short" }).replace(/\.$/, "");
}
function mmRange(r) {
  if (r.precipitation_max == null && r.precipitation_min == null) return "";
  const lo = r.precipitation_min || 0, hi = r.precipitation_max || 0;
  return `${fmt(lo, 0)} - ${fmt(hi, 0)} mm`;
}

/** Subscribes to the daily (and optionally hourly) forecast of one entity. */
function subscribeForecast(hass, entity, type, cb) {
  try {
    return hass.connection.subscribeMessage((msg) => cb(msg.forecast || []), { type: "weather/subscribe_forecast", forecast_type: type, entity_id: entity });
  } catch (e) {
    return null;
  }
}

/** Shared editor: an ha-form with the given schema and labels. */
class SwissMeteoBaseEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...this.constructor.defaults, ...config };
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    this._render();
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
    this._form.schema = this.constructor.schema;
    const l = lang(this._hass);
    this._form.computeLabel = (s) => (LIST_EDITOR_LABELS[s.name] && (LIST_EDITOR_LABELS[s.name][l] || LIST_EDITOR_LABELS[s.name].en)) || s.name;
  }
}

/* ------------------------------------------------------------------------
 * Daily list card — the look of the MeteoSwiss local forecast page:
 * weekday, symbol, low and high in boxes, precipitation with its range,
 * and the wind / sunshine toggles.
 * ---------------------------------------------------------------------- */

class SwissMeteoDailyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._daily = null;
    this._unsub = null;
    this._lastState = null;
    this._wind = null;
    this._sun = null;
  }
  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = { days: 9, show_wind: false, show_sunshine: false, show_toggles: true, theme: "meteo", ...config };
    this._subscribed = false;
    this._render();
  }
  static getConfigElement() {
    return document.createElement("swiss-meteo-daily-card-editor");
  }
  static getStubConfig(hass, entities) {
    const entity = (entities || []).find((e) => e.startsWith("weather.swiss_meteo")) || (entities || []).find((e) => e.startsWith("weather.")) || "";
    return { entity, days: 8 };
  }
  getCardSize() {
    return 1 + Math.ceil((Number(this._config.days) || 9) * 0.8);
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._subscribed && hass.connection && this._config) this._subscribe();
    const state = hass.states[this._config.entity];
    const stamp = state ? state.last_updated : "none";
    if (stamp !== this._lastState) {
      this._lastState = stamp;
      this._render();
    }
  }
  connectedCallback() {
    if (this._hass && !this._subscribed) this._subscribe();
  }
  disconnectedCallback() {
    if (this._unsub) Promise.resolve(this._unsub).then((u) => typeof u === "function" && u()).catch(() => {});
    this._unsub = null;
    this._subscribed = false;
  }
  _subscribe() {
    this.disconnectedCallback();
    this._subscribed = true;
    this._unsub = subscribeForecast(this._hass, this._config.entity, "daily", (f) => {
      this._daily = f;
      this._render();
    });
  }
  _render() {
    if (!this._hass || !this._config) return;
    const hass = this._hass;
    const state = hass.states[this._config.entity];
    const a = state ? state.attributes : {};
    const showWind = this._wind ?? !!this._config.show_wind;
    const showSun = this._sun ?? !!this._config.show_sunshine;
    let title = this._config.title;
    if (!title) {
      title = a.point_name || (state ? state.attributes.friendly_name : this._config.entity);
      if (a.elevation != null) title += `, ${fmt(a.elevation)} ${LL(hass, "asl")}`;
    }
    const rows = (this._daily || []).slice(0, Math.max(1, Math.min(9, Number(this._config.days) || 9)));
    const lines = rows.map((r, i) => {
      const d = new Date(r.datetime);
      const icon = iconFor(r.symbol, r.condition, false, this._config.animated);
      const extra = [];
      if (showWind && r.wind_speed != null) extra.push(`<span class="x"><img src="${iconUrl("wind", this._config.animated)}" alt="" />${fmt(r.wind_speed)} km/h${r.wind_gust_speed != null ? ` <span class="dim">${esc(LL(hass, "gusts"))} ${fmt(r.wind_gust_speed)}</span>` : ""}</span>`);
      if (showSun && r.sunshine_hours != null) extra.push(`<span class="x"><img src="${iconUrl("clear-day", this._config.animated)}" alt="" />${fmt(r.sunshine_hours, 1)} h</span>`);
      return `<div class="row${i === 0 ? " first" : ""}">
        <div class="wd">${esc(dayLabel(hass, d, i))}</div>
        <img class="sym" src="${icon}" alt="${esc(r.condition || "")}" />
        <div class="temps"><span class="box lo">${fmt(r.templow)}°</span><span class="box hi">${fmt(r.temperature)}°</span></div>
        <img class="drops" src="${iconUrl("raindrops", this._config.animated)}" alt="" />
        <div class="mm"><div class="val">${r.precipitation != null ? fmt(r.precipitation, 0) + " mm" : "–"}</div><div class="rng">${esc(mmRange(r))}</div></div>
        ${extra.length ? `<div class="extra">${extra.join("")}</div>` : ""}
      </div>`;
    });
    const toggles = this._config.show_toggles
      ? `<div class="toggles">
          <label><span class="sw ${showWind ? "on" : ""}" data-t="wind"><span></span></span><img src="${iconUrl("windsock", this._config.animated)}" alt="" />${esc(LL(hass, "wind"))}</label>
          <label><span class="sw ${showSun ? "on" : ""}" data-t="sun"><span></span></span><img src="${iconUrl("clear-day", this._config.animated)}" alt="" />${esc(LL(hass, "sunshine"))}</label>
        </div>`
      : "";
    const empty = !state || state.state === "unavailable" ? `<div class="empty">${esc(L(hass, "unavailable"))}</div>` : "";
    this.shadowRoot.innerHTML = `${this._style()}<ha-card class="${esc(this._config.theme)}">
      <div class="head">${esc(title)}</div>
      ${empty}
      <div class="list">${lines.join("")}</div>
      ${toggles}
      <div class="foot">${esc(LL(hass, "source"))}</div>
    </ha-card>`;
    this.shadowRoot.querySelector(".head")?.addEventListener("click", () => {
      const ev = new Event("hass-more-info", { bubbles: true, composed: true });
      ev.detail = { entityId: this._config.entity };
      this.dispatchEvent(ev);
    });
    for (const sw of this.shadowRoot.querySelectorAll(".sw")) {
      sw.addEventListener("click", () => {
        if (sw.dataset.t === "wind") this._wind = !showWind;
        else this._sun = !showSun;
        this._render();
      });
    }
  }
  _style() {
    return `<style>
      :host { display: block; }
      ha-card { padding: 16px 16px 10px; overflow: hidden;
        --sm-bg: var(--card-background-color); --sm-panel: var(--secondary-background-color, rgba(128,128,128,0.08));
        --sm-line: var(--divider-color, rgba(128,128,128,0.3)); --sm-box: rgba(128,128,128,0.18); --sm-text: var(--primary-text-color);
        --sm-dim: var(--secondary-text-color); --sm-accent: var(--primary-color, #1f5fd6); }
      ha-card.meteo { background: #1c2733; color: #fff;
        --sm-bg: #1c2733; --sm-panel: #2b3a4a; --sm-line: #1c2733; --sm-box: #4a5f75; --sm-text: #fff; --sm-dim: #c3ccd6; --sm-accent: #ffffff; }
      .head { font-size: 1.6em; font-weight: 700; line-height: 1.15; margin-bottom: 12px; cursor: pointer; color: var(--sm-text); }
      .empty { opacity: 0.7; padding: 8px 0; }
      .list { background: var(--sm-panel); border-radius: 4px; overflow: hidden; }
      .row { display: grid; grid-template-columns: 3.4em 56px auto 28px 1fr; grid-template-areas: "wd sym temps drops mm" "extra extra extra extra extra";
        align-items: center; gap: 0 8px; padding: 8px 12px; border-top: 2px solid var(--sm-line); color: var(--sm-text); }
      .row.first { border-top: none; }
      .wd { grid-area: wd; font-size: 1.05em; }
      .sym { grid-area: sym; width: 56px; height: 56px; }
      .temps { grid-area: temps; display: flex; gap: 6px; }
      .box { display: inline-block; min-width: 2.6em; text-align: center; padding: 6px 4px; border-radius: 3px; background: var(--sm-box); font-size: 1.05em; }
      .drops { grid-area: drops; width: 28px; height: 28px; justify-self: end; }
      .mm { grid-area: mm; text-align: right; }
      .mm .val { font-size: 1.15em; font-weight: 500; }
      .mm .rng { font-size: 0.85em; color: var(--sm-dim); }
      .extra { grid-area: extra; display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 0.9em; padding: 2px 0 0 calc(3.4em + 8px); color: var(--sm-dim); }
      .x { display: inline-flex; align-items: center; gap: 2px; }
      .x img { width: 26px; height: 26px; }
      .dim { opacity: 0.75; margin-left: 4px; }
      .toggles { display: flex; flex-wrap: wrap; gap: 10px 28px; margin: 18px 0 6px 4px; color: var(--sm-text); font-size: 1.05em; }
      .toggles label { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; }
      .toggles img { width: 30px; height: 30px; }
      .sw { position: relative; width: 44px; height: 26px; border-radius: 13px; background: #3a4a5a; display: inline-block; transition: background 0.2s; }
      ha-card:not(.meteo) .sw { background: rgba(128,128,128,0.4); }
      .sw span { position: absolute; top: 3px; left: 3px; width: 20px; height: 20px; border-radius: 50%; background: #fff; transition: left 0.2s; }
      .sw.on { background: var(--sm-accent); }
      ha-card.meteo .sw.on { background: #4a7ddb; }
      .sw.on span { left: 21px; }
      .foot { font-size: 0.72em; color: var(--sm-dim); margin-top: 8px; text-align: right; }
    </style>`;
  }
}
customElements.define("swiss-meteo-daily-card", SwissMeteoDailyCard);

class SwissMeteoDailyCardEditor extends SwissMeteoBaseEditor {}
SwissMeteoDailyCardEditor.defaults = { animated: true, days: 8, show_wind: false, show_sunshine: false, show_toggles: true, theme: "meteo" };
SwissMeteoDailyCardEditor.schema = [
  { name: "entity", required: true, selector: { entity: { domain: "weather" } } },
  { name: "title", selector: { text: {} } },
  { name: "days", selector: { number: { min: 1, max: 9, mode: "box" } } },
  { name: "show_wind", selector: { boolean: {} } },
  { name: "show_sunshine", selector: { boolean: {} } },
  { name: "show_toggles", selector: { boolean: {} } },
  { name: "theme", selector: { select: { mode: "dropdown", options: [{ value: "meteo", label: "Swiss Meteo" }, { value: "ha", label: "Home Assistant" }] } } },
  { name: "animated", selector: { boolean: {} } },
];
customElements.define("swiss-meteo-daily-card-editor", SwissMeteoDailyCardEditor);

/* ------------------------------------------------------------------------
 * Map card — Switzerland with a pill per configured place: symbol, name,
 * low and high of the chosen day. The outline and the lakes come from
 * Natural Earth (public domain), projected equirectangular.
 * ---------------------------------------------------------------------- */

const MAP = {"W":1000.0,"H":668.6,"LON0":5.85,"LAT1":47.9,"KX":0.68423,"SX":310.9572,"ch":"M979.5,322.0 977.6,334.8 971.7,342.4 974.2,355.8 971.6,359.8 968.0,362.1 966.9,372.9 962.5,378.8 961.5,381.7 963.3,387.7 967.2,392.2 976.2,393.2 980.7,396.9 982.3,402.9 982.1,410.9 980.4,418.6 977.4,423.6 973.6,424.4 958.4,420.3 950.9,421.0 945.8,419.5 941.7,415.0 932.9,411.9 932.0,408.6 933.1,402.2 932.7,398.7 929.3,395.9 923.9,395.9 901.7,402.9 898.1,415.3 889.9,425.1 889.0,440.3 890.5,444.3 892.3,445.6 888.6,452.1 891.9,456.3 911.4,462.1 912.9,465.5 911.3,472.3 905.3,478.5 902.6,485.7 902.5,488.5 905.3,494.6 914.1,503.7 916.8,509.2 914.0,515.2 908.1,518.9 899.1,522.4 892.1,522.3 891.9,515.2 889.7,509.9 881.3,502.4 878.2,498.1 875.3,480.1 870.0,476.6 865.6,475.4 861.5,475.1 852.2,476.7 833.6,485.5 830.9,484.9 825.7,481.8 823.4,481.7 821.1,484.3 820.9,493.9 817.7,498.4 813.7,500.1 789.3,499.8 784.4,498.0 779.8,494.9 777.1,491.1 772.9,479.9 764.8,474.1 762.7,435.9 757.6,438.8 754.4,444.9 752.0,445.8 745.0,439.9 744.9,436.0 740.6,434.9 730.3,436.2 726.2,440.0 722.5,447.5 720.8,455.1 722.9,459.3 725.7,461.3 725.6,472.7 728.8,487.8 727.4,494.6 721.2,507.8 718.1,518.9 713.7,524.4 708.8,527.4 704.9,537.2 689.5,547.9 685.6,553.8 684.7,557.9 685.2,564.9 684.5,568.7 682.8,571.6 676.1,574.3 670.7,578.6 669.7,582.1 673.5,593.0 666.5,599.5 666.1,601.9 668.8,605.0 670.6,610.7 672.5,613.6 681.2,617.1 683.6,622.2 682.8,627.5 677.5,638.1 670.7,646.6 664.3,645.3 657.4,642.2 648.9,644.8 651.9,632.5 651.5,627.1 642.8,607.3 639.9,604.2 627.7,597.5 620.8,596.1 625.7,585.0 631.8,577.5 635.0,570.2 629.6,562.9 626.4,561.8 616.4,561.4 613.2,557.4 611.5,556.8 605.3,561.2 601.6,561.0 591.7,555.2 585.5,552.6 572.1,532.5 566.0,526.2 554.6,520.9 550.7,517.6 548.3,512.6 547.5,505.0 548.2,497.0 551.7,480.9 552.3,462.6 551.4,455.6 548.5,451.3 542.4,450.2 530.5,452.8 524.7,456.0 520.2,460.8 518.4,464.8 520.6,467.2 520.7,470.3 517.3,475.7 508.9,480.7 498.4,494.7 494.0,497.8 484.8,499.9 480.2,502.0 476.0,506.3 473.0,512.0 478.7,517.5 485.0,529.9 485.6,541.3 481.0,551.3 471.7,559.5 465.0,560.8 462.8,562.5 461.3,565.7 459.7,581.6 457.1,587.5 454.4,591.0 450.9,593.0 435.8,596.4 432.7,598.9 430.4,603.4 429.8,609.4 425.5,609.6 424.2,615.9 421.5,617.4 416.5,616.2 410.7,616.3 400.4,612.5 395.0,613.9 392.3,613.0 388.0,606.3 381.5,601.3 359.8,595.8 356.3,597.6 351.9,604.3 347.4,604.9 341.1,607.6 328.5,617.0 321.7,619.5 305.7,617.7 283.8,628.0 277.4,629.2 270.4,629.3 263.9,628.0 258.9,625.0 247.9,611.6 242.1,593.0 226.6,575.7 221.8,573.5 216.9,577.1 213.0,575.4 213.4,567.2 213.1,564.1 212.5,564.4 216.6,558.3 216.9,555.9 213.6,552.7 196.7,548.9 194.8,543.7 196.8,533.0 200.5,521.9 208.0,507.0 203.2,498.6 195.6,490.5 191.6,483.4 192.7,479.8 198.3,473.1 199.8,467.9 199.4,462.0 197.4,458.9 194.2,457.3 162.5,449.1 148.3,448.6 134.7,451.3 116.5,463.9 109.6,465.7 102.6,466.0 96.1,468.2 89.2,474.2 78.6,488.5 77.5,492.7 82.5,507.5 85.6,510.0 89.1,508.3 90.6,509.0 91.7,516.2 86.2,522.1 72.6,531.2 61.8,544.1 54.9,547.7 47.6,544.4 37.9,544.8 28.3,547.1 23.2,550.2 28.3,537.7 22.3,528.7 23.1,524.9 41.0,515.2 45.1,515.8 51.0,514.2 51.9,512.1 51.8,505.9 53.3,497.1 60.9,479.1 60.7,475.6 54.9,467.5 43.5,460.4 45.9,458.0 46.3,456.0 44.7,447.8 45.6,444.3 48.0,441.7 55.4,428.9 62.9,419.3 57.8,413.5 57.1,409.4 60.0,405.6 88.6,379.3 103.8,370.8 111.5,362.7 118.6,358.9 123.2,354.2 124.0,346.4 120.7,341.4 127.0,324.1 126.6,316.4 122.9,308.1 126.1,297.2 136.4,291.2 159.3,284.0 173.5,273.2 178.4,266.2 175.8,260.5 178.7,255.5 180.7,253.5 186.0,251.6 186.8,249.7 190.6,247.5 190.4,242.2 196.8,240.0 210.7,227.1 214.7,220.5 220.9,214.2 235.4,203.6 234.5,195.9 235.9,189.5 239.9,185.4 243.0,184.7 246.1,180.6 252.5,177.4 254.1,174.0 251.9,170.8 245.5,165.4 241.6,167.3 216.3,169.7 220.0,160.9 223.1,156.8 228.6,153.6 229.0,147.7 234.5,146.5 238.0,144.5 242.8,139.2 239.0,127.8 246.8,124.6 250.6,126.6 256.2,127.4 266.8,125.5 277.4,128.6 283.2,128.0 279.3,136.9 280.5,141.9 285.1,144.7 291.4,146.6 293.7,149.6 295.3,150.3 304.8,146.5 310.4,145.3 325.2,145.9 331.1,143.6 335.3,138.1 336.0,135.2 332.9,129.3 332.8,127.4 335.3,126.7 344.1,130.0 347.8,126.6 348.1,124.9 346.3,122.0 346.2,119.8 351.3,119.0 352.2,117.2 352.2,114.1 347.4,111.2 356.7,103.7 361.8,100.9 380.2,94.8 385.0,94.4 382.2,102.1 380.0,104.3 374.4,104.2 385.4,110.0 390.1,110.6 407.8,107.0 411.8,104.7 419.1,94.7 422.1,96.2 435.8,97.1 437.1,98.4 438.8,105.6 466.4,105.6 476.0,103.4 478.1,102.0 481.7,97.1 488.0,93.3 491.9,92.1 495.5,88.4 507.0,86.5 510.9,86.4 518.8,88.4 522.6,95.7 524.7,97.1 532.8,99.2 546.4,99.3 553.0,98.2 555.7,91.4 562.2,87.1 568.6,86.5 571.9,89.5 576.7,96.6 579.6,95.6 581.0,93.2 580.9,81.2 583.7,80.0 584.1,82.5 585.5,83.2 586.7,75.8 578.3,73.7 568.0,75.5 558.7,80.7 555.0,80.9 545.1,74.3 540.7,72.9 542.1,69.6 540.6,64.6 540.9,62.3 543.0,60.0 550.6,55.0 552.2,48.8 556.1,42.3 557.8,41.3 571.6,39.2 574.8,37.5 572.8,32.6 576.2,30.7 581.5,31.0 585.5,32.8 586.7,42.8 588.8,44.4 591.5,42.7 592.6,35.9 594.5,33.9 597.2,34.8 602.5,43.9 609.2,44.3 610.6,47.5 606.5,54.9 609.1,59.5 610.0,63.9 621.3,63.7 619.5,61.8 621.4,55.7 627.1,56.0 634.1,60.0 639.6,65.1 635.7,66.0 635.7,68.2 645.0,75.8 650.3,77.2 658.6,76.4 666.3,74.0 669.7,70.3 673.7,68.8 697.5,71.4 709.2,71.4 712.1,75.8 720.1,75.8 728.3,77.7 786.7,113.6 788.3,121.0 794.6,130.4 802.5,134.0 808.6,139.3 808.4,152.5 806.3,157.2 798.1,167.5 795.2,177.9 787.9,186.6 777.6,204.1 773.9,214.6 773.4,225.0 779.1,239.6 779.2,246.3 777.2,250.4 771.5,257.1 771.7,260.0 789.5,263.6 793.9,262.2 797.9,263.2 809.0,261.8 812.6,262.4 852.8,275.0 852.4,278.6 855.4,280.2 853.4,295.7 853.7,298.6 856.4,302.4 861.7,306.5 884.4,313.8 892.7,321.7 897.5,324.4 906.7,327.4 911.1,327.6 916.6,326.0 925.8,321.3 928.0,318.1 929.8,309.2 933.0,303.7 936.5,303.1 940.6,304.1 945.9,303.9 946.0,298.1 949.7,291.0 955.1,284.8 961.3,281.3 963.6,281.3 967.0,284.4 971.4,291.6 980.5,299.6 981.7,304.8 979.0,315.4 979.5,322.0Z","lakes":"M714.1,241.8 699.6,238.6 698.2,236.1 702.2,234.9 719.6,236.5 734.5,239.2 729.8,241.3 714.1,241.8ZM565.3,256.4 559.4,250.6 558.7,241.5 555.1,231.3 555.8,221.8 562.2,222.3 566.0,229.8 563.7,240.9 569.5,252.3 568.9,256.8 565.3,256.4ZM264.2,262.7 261.0,261.3 292.7,236.1 294.3,236.7 284.5,255.8 277.3,262.7 270.8,265.2 264.2,262.7ZM611.3,203.3 619.5,204.5 629.0,203.4 634.6,209.1 656.8,208.9 653.6,212.2 643.2,213.5 634.8,217.0 621.0,212.9 613.0,213.9 608.2,212.1 599.1,203.3 592.9,199.2 587.3,197.3 583.1,193.9 576.2,180.7 571.7,167.7 574.9,167.3 584.7,185.4 596.3,194.5 611.3,203.3ZM220.6,313.6 213.5,321.8 191.4,338.0 187.3,337.3 172.3,343.9 168.8,341.5 169.6,336.7 178.6,330.7 188.1,322.0 196.1,311.7 207.0,300.4 214.0,296.0 217.7,290.3 219.2,285.3 241.5,273.7 249.4,276.4 253.9,279.1 252.1,286.0 220.6,313.6ZM256.7,306.9 253.4,304.4 255.5,298.4 263.6,292.7 269.5,290.7 272.2,292.8 267.8,300.0 260.3,306.1 256.7,306.9ZM532.6,264.7 539.6,261.9 547.0,256.7 549.0,258.8 545.3,264.5 547.6,267.9 556.5,270.5 561.2,276.5 565.4,279.6 571.8,279.9 577.1,278.9 581.0,277.1 584.9,278.0 588.4,286.7 588.7,300.0 590.3,304.3 588.7,309.4 585.2,311.0 582.5,300.8 582.4,293.9 584.0,284.9 583.2,281.4 570.6,287.2 562.5,288.7 547.3,283.0 550.8,279.9 545.7,276.8 534.0,279.3 525.9,289.0 520.0,291.8 517.7,290.8 524.5,281.6 524.0,274.2 528.8,276.3 529.6,271.3 527.8,261.8 529.4,261.4 532.6,264.7ZM697.7,627.4 700.3,623.5 698.1,611.4 702.5,601.5 719.4,592.3 720.7,588.8 720.5,582.0 722.3,576.2 727.8,568.0 730.9,549.1 735.7,543.7 742.4,540.3 744.4,537.3 749.0,536.4 751.0,540.5 749.6,544.6 740.1,549.1 737.7,552.5 737.5,558.5 735.2,563.7 736.8,569.9 735.7,574.2 730.8,582.8 738.4,615.4 742.8,620.8 747.5,623.7 757.1,640.1 758.1,647.0 755.4,646.9 754.5,640.7 751.4,634.7 746.0,627.7 736.1,620.1 730.2,607.2 726.5,595.6 722.7,595.5 717.7,600.8 712.4,604.3 706.0,606.5 703.0,611.5 703.4,622.2 701.6,631.0 697.3,632.3 692.8,636.2 686.4,645.9 684.6,644.7 685.8,639.9 688.2,636.2 693.0,630.5 697.7,627.4ZM78.3,652.4 74.6,641.5 64.1,634.8 61.6,620.1 63.2,617.7 68.7,623.7 72.1,633.4 74.6,637.1 78.9,640.7 81.3,646.1 80.4,650.4 78.3,652.4ZM662.9,605.5 666.6,615.2 665.4,617.5 661.7,609.8 654.9,613.2 649.3,618.0 646.0,598.8 649.6,591.0 650.3,594.7 649.5,606.3 650.8,610.6 654.2,610.6 659.9,598.6 660.3,591.4 661.8,587.0 668.0,587.4 674.8,583.6 684.4,580.4 696.1,578.0 693.7,582.6 684.8,585.3 678.6,585.5 671.7,589.8 664.1,598.6 662.9,605.5ZM437.1,373.7 434.9,371.2 454.1,355.0 458.6,352.9 463.9,352.9 467.7,355.9 465.5,358.6 459.7,360.8 445.6,370.2 437.1,373.7ZM400.9,381.8 384.4,369.8 380.3,364.3 379.4,359.8 381.9,356.8 402.0,372.1 410.1,375.8 418.4,377.3 419.6,381.2 410.0,384.2 400.9,381.8ZM889.0,694.7 881.5,692.3 878.2,693.0 876.9,692.0 880.8,688.8 893.6,685.8 893.6,675.3 892.7,667.6 890.9,662.0 900.1,644.4 903.6,647.2 903.1,653.1 899.7,655.4 898.2,657.9 906.5,678.5 904.1,684.9 897.2,691.4 889.0,694.7ZM4.1,696.0 1.8,690.1 2.0,678.4 -5.9,652.3 -5.2,649.4 -1.4,649.3 2.5,654.7 7.8,669.8 6.6,672.8 7.9,676.2 9.6,690.7 7.7,697.1 4.1,696.0ZM217.3,448.2 226.9,453.4 230.9,459.3 226.4,465.1 216.5,465.7 180.3,459.3 138.2,463.6 133.9,469.9 118.8,477.2 115.7,481.6 113.6,482.6 111.9,481.8 107.5,475.3 94.6,474.5 82.4,493.7 70.8,516.6 60.3,527.2 61.8,522.3 64.5,518.9 66.0,507.2 69.5,497.5 99.7,450.6 103.1,447.4 107.0,445.5 121.1,443.7 137.2,431.2 140.6,429.9 159.1,428.4 163.9,429.3 217.3,448.2ZM823.1,109.9 826.0,112.4 828.6,118.2 817.0,118.2 814.1,124.6 808.3,124.6 807.0,123.9 806.6,121.1 805.3,120.6 799.6,124.6 796.4,124.6 793.4,123.9 787.8,120.6 780.4,126.6 775.4,128.1 754.9,110.7 751.2,101.3 749.2,99.2 714.2,78.6 709.1,71.3 714.1,70.8 713.9,67.9 709.1,60.9 704.6,47.6 701.8,43.7 698.1,41.1 685.8,35.0 678.7,27.7 677.0,24.6 685.5,25.9 707.7,41.8 715.1,43.7 718.4,54.5 738.8,67.8 742.8,69.0 756.0,70.0 767.4,75.7 774.1,76.5 778.1,80.2 781.2,89.4 784.6,93.6 787.8,95.3 796.7,97.0 805.3,101.3 814.1,107.6 823.1,109.9ZM684.3,55.0 692.3,62.0 697.3,71.3 673.6,68.7 669.7,70.2 666.2,73.9 658.4,76.4 650.1,77.1 644.9,75.7 652.1,75.7 656.4,72.1 667.3,66.4 671.2,60.9 658.1,51.6 659.4,47.8 660.9,47.4 664.1,50.1 671.2,52.2 671.2,50.1 666.7,47.8 666.7,45.9 684.3,55.0ZM637.5,538.2 638.1,539.5 636.5,542.8 623.4,554.3 616.2,562.0 615.3,570.9 617.7,585.4 614.5,592.5 610.7,596.6 595.4,607.9 589.1,614.9 586.5,620.1 586.0,627.3 589.7,638.4 589.7,644.6 587.9,648.6 579.8,654.8 578.8,659.5 580.3,663.4 589.5,676.2 587.7,677.2 583.9,674.8 580.6,671.1 575.7,661.3 574.2,655.8 578.1,647.3 579.7,636.8 578.0,631.2 568.3,622.6 562.3,610.2 564.6,608.5 572.5,611.7 576.7,611.9 588.4,604.8 601.8,587.6 605.6,584.5 609.3,578.8 609.3,574.7 606.5,565.6 606.5,562.2 608.7,556.5 613.5,550.2 626.6,539.7 634.3,537.4 637.5,538.2ZM1064.9,623.3 1067.6,628.2 1068.1,634.3 1066.5,641.3 1063.4,648.8 1036.2,693.3 1030.2,716.0 1029.7,722.7 1034.2,721.1 1034.7,726.0 1038.6,740.6 1032.8,760.7 1032.1,762.0 1027.7,759.6 1022.5,758.9 1017.1,756.6 1013.2,752.1 1012.4,744.9 1011.2,752.2 1007.0,755.0 1002.0,754.3 997.7,751.2 999.3,749.1 995.8,747.2 991.8,746.9 991.8,744.9 993.5,744.3 1003.7,733.7 1005.0,731.0 1001.2,721.0 1005.0,719.2 1003.8,715.6 1001.5,713.4 994.8,712.7 1011.2,702.1 1016.6,695.7 1035.0,678.8 1038.2,674.7 1045.4,657.1 1049.6,653.0 1058.3,639.4 1062.1,626.7 1064.9,623.3Z"};

function mapXY(lat, lon) {
  const x = ((lon - MAP.LON0) * MAP.KX * MAP.SX) / MAP.W;
  const y = ((MAP.LAT1 - lat) * MAP.SX) / MAP.H;
  return [Math.min(0.97, Math.max(0.03, x)), Math.min(0.97, Math.max(0.03, y))];
}

class SwissMeteoMapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._daily = {};
    this._unsubs = {};
    this._lastStamp = null;
  }
  setConfig(config) {
    this._config = { day: 0, show_names: true, ...(config || {}) };
    this._wanted = null;
    this._render();
  }
  static getConfigElement() {
    return document.createElement("swiss-meteo-map-card-editor");
  }
  static getStubConfig() {
    return { day: 0 };
  }
  getCardSize() {
    return 6;
  }
  _entities() {
    const configured = this._config.entities;
    if (Array.isArray(configured) && configured.length) return configured.map((e) => (typeof e === "string" ? e : e.entity)).filter(Boolean);
    return Object.keys(this._hass.states).filter((e) => e.startsWith("weather.swiss_meteo")).sort();
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const ents = this._entities();
    const key = ents.join(",");
    if (key !== this._wanted && hass.connection) {
      this._wanted = key;
      this._resubscribe(ents);
    }
    const stamp = ents.map((e) => (hass.states[e] ? hass.states[e].last_updated : "x")).join("|");
    if (stamp !== this._lastStamp) {
      this._lastStamp = stamp;
      this._render();
    }
  }
  connectedCallback() {
    if (this._hass && this._config) {
      this._wanted = null;
      this.hass = this._hass;
    }
  }
  disconnectedCallback() {
    this._resubscribe([]);
    this._wanted = null;
  }
  _resubscribe(ents) {
    for (const [e, p] of Object.entries(this._unsubs)) {
      if (!ents.includes(e)) {
        Promise.resolve(p).then((u) => typeof u === "function" && u()).catch(() => {});
        delete this._unsubs[e];
        delete this._daily[e];
      }
    }
    for (const e of ents) {
      if (this._unsubs[e]) continue;
      const p = subscribeForecast(this._hass, e, "daily", (f) => {
        this._daily[e] = f;
        this._render();
      });
      if (p) this._unsubs[e] = p;
    }
  }
  _render() {
    if (!this._hass || !this._config) return;
    const hass = this._hass;
    const l = lang(hass);
    const dayIdx = Math.max(0, Math.min(8, Number(this._config.day) || 0));
    const ents = this._entities();
    let date = null;
    const pills = [];
    for (const e of ents) {
      const s = hass.states[e];
      if (!s || s.attributes.latitude == null || s.attributes.longitude == null) continue;
      const rows = this._daily[e] || [];
      const r = rows[dayIdx];
      if (r && !date) date = new Date(r.datetime);
      const [x, y] = mapXY(Number(s.attributes.latitude), Number(s.attributes.longitude));
      const icon = r ? iconFor(r.symbol, r.condition, false, this._config.animated) : iconFor(s.attributes.symbol, s.state, false, this._config.animated);
      const name = this._config.show_names ? esc(s.attributes.point_name || s.attributes.friendly_name) : "";
      pills.push(`<div class="pill" style="left:${(x * 100).toFixed(2)}%;top:${(y * 100).toFixed(2)}%" data-e="${esc(e)}">
        <img src="${icon}" alt="" />
        <div class="body">${name ? `<div class="name">${name}</div>` : ""}<div class="t"><span>${fmt(r ? r.templow : null)}°</span><span>${fmt(r ? r.temperature : null)}°</span></div></div>
      </div>`);
    }
    let title = this._config.title;
    if (!title) {
      const when = dayIdx === 0 ? LL(hass, "map_today") : dayIdx === 1 ? LL(hass, "map_tomorrow") : date ? date.toLocaleDateString(l, { weekday: "long" }) : "";
      const ds = date ? date.toLocaleDateString(l, { day: "numeric", month: "long", year: "numeric" }) : "";
      title = `${LL(hass, "map_title")} ${when}${ds ? ", " + ds : ""}`;
    }
    const empty = ents.length ? "" : `<div class="empty">${esc(LL(hass, "no_entities"))}</div>`;
    this.shadowRoot.innerHTML = `${this._style()}<ha-card>
      <div class="map">
        <svg viewBox="0 0 ${MAP.W} ${MAP.H}" preserveAspectRatio="none">
          <defs><clipPath id="ch"><path d="${MAP.ch}" /></clipPath>
          <filter id="sh" x="-5%" y="-5%" width="115%" height="115%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#000" flood-opacity="0.45" /></filter></defs>
          <path class="land" d="${MAP.ch}" filter="url(#sh)" />
          <g clip-path="url(#ch)"><path class="lake" d="${MAP.lakes}" /></g>
          <path class="border" d="${MAP.ch}" />
        </svg>
        <div class="title">${esc(title)}</div>
        ${pills.join("")}
        ${empty}
        <div class="info" title="${esc(LL(hass, "source"))}">i</div>
      </div>
    </ha-card>`;
    for (const p of this.shadowRoot.querySelectorAll(".pill")) {
      p.addEventListener("click", () => {
        const ev = new Event("hass-more-info", { bubbles: true, composed: true });
        ev.detail = { entityId: p.dataset.e };
        this.dispatchEvent(ev);
      });
    }
  }
  _style() {
    return `<style>
      :host { display: block; }
      ha-card { overflow: hidden; background: #4b5661; color: #fff; }
      .map { position: relative; width: 100%; aspect-ratio: ${MAP.W} / ${MAP.H}; background: radial-gradient(ellipse at 50% 40%, #5a6773 0%, #414b55 70%, #39424b 100%); container-type: inline-size; }
      .map svg { position: absolute; inset: 0; width: 100%; height: 100%; }
      .land { fill: #86c3a1; }
      .lake { fill: #a9d9f3; }
      .border { fill: none; stroke: #d6efe0; stroke-width: 1.2; opacity: 0.6; }
      .title { position: absolute; left: 4%; top: 4%; font-weight: 700; font-size: 4.2cqw; text-shadow: 0 1px 3px rgba(0,0,0,0.5); }
      .pill { position: absolute; transform: translate(-16%, -50%); display: flex; align-items: center; cursor: pointer; filter: drop-shadow(0 3px 4px rgba(0,0,0,0.45)); }
      .pill img { width: 11cqw; height: 11cqw; margin-right: -3.5cqw; position: relative; z-index: 1; }
      .pill .body { background: linear-gradient(180deg, #2f6cf0 0%, #1f4fd2 100%); border-radius: 2.2cqw; padding: 0.8cqw 1.6cqw 0.8cqw 4.4cqw; display: flex; flex-direction: column; gap: 0.4cqw; }
      .pill .name { font-size: 3.1cqw; font-weight: 500; line-height: 1.1; white-space: nowrap; }
      .pill .t { display: flex; gap: 0.6cqw; }
      .pill .t span { background: #1a3fb2; border-radius: 0.6cqw; padding: 0.3cqw 1cqw; font-size: 2.9cqw; min-width: 4.5cqw; text-align: center; }
      .empty { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); background: rgba(0,0,0,0.5); padding: 8px 12px; border-radius: 6px; font-size: 0.9em; }
      .info { position: absolute; right: 3%; bottom: 4%; width: 3.6cqw; height: 3.6cqw; border-radius: 50%; border: 0.3cqw solid rgba(255,255,255,0.7); font-size: 2.6cqw; line-height: 3.3cqw; text-align: center; opacity: 0.8; font-family: serif; font-weight: 700; }
    </style>`;
  }
}
customElements.define("swiss-meteo-map-card", SwissMeteoMapCard);

class SwissMeteoMapCardEditor extends SwissMeteoBaseEditor {}
SwissMeteoMapCardEditor.defaults = { animated: true, day: 0, show_names: true };
SwissMeteoMapCardEditor.schema = [
  { name: "entities", selector: { entity: { domain: "weather", multiple: true } } },
  { name: "title", selector: { text: {} } },
  { name: "day", selector: { number: { min: 0, max: 8, mode: "box" } } },
  { name: "show_names", selector: { boolean: {} } },
  { name: "animated", selector: { boolean: {} } },
];
customElements.define("swiss-meteo-map-card-editor", SwissMeteoMapCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "swiss-meteo-daily-card",
  name: "Swiss Meteo – daily list",
  description: "Nine-day list in the MeteoSwiss look: symbol, low/high, precipitation with range, wind and sunshine.",
  preview: true,
});
window.customCards.push({
  type: "swiss-meteo-map-card",
  name: "Swiss Meteo – map",
  description: "Switzerland with a forecast pill for every configured place.",
  preview: true,
});

window.customCards = window.customCards || [];
window.customCards.push({
  type: "swiss-meteo-card",
  name: "Swiss Meteo",
  description: "MeteoSwiss forecast: current values, hourly chart with uncertainty, nine-day strip.",
  preview: true,
});

/* ------------------------------------------------------------------------
 * Forecast card — the drop-in for Home Assistant's own weather-forecast
 * card (same options: forecast_type, show_current, show_forecast), drawn
 * in the MeteoSwiss look: the current conditions on top, below a row of
 * days (symbol, low and high in boxes, precipitation) or hours (symbol,
 * temperature, precipitation).
 * ---------------------------------------------------------------------- */

class SwissMeteoForecastCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._forecast = null;
    this._unsub = null;
    this._lastState = null;
  }
  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = { forecast_type: "daily", show_current: true, show_forecast: true, columns: 0, size: "normal", animated: true, theme: "meteo", ...config };
    this._subscribed = false;
    this._forecast = null;
    this._render();
  }
  static getConfigElement() {
    return document.createElement("swiss-meteo-forecast-card-editor");
  }
  static getStubConfig(hass, entities) {
    const entity = (entities || []).find((e) => e.startsWith("weather.swiss_meteo")) || (entities || []).find((e) => e.startsWith("weather.")) || "";
    return { entity, forecast_type: "daily" };
  }
  getCardSize() {
    return (this._config.show_current ? 2 : 0) + (this._config.show_forecast ? 3 : 0);
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._subscribed && hass.connection && this._config) this._subscribe();
    const state = hass.states[this._config.entity];
    const stamp = state ? state.last_updated : "none";
    if (stamp !== this._lastState) {
      this._lastState = stamp;
      this._render();
    }
  }
  connectedCallback() {
    if (this._hass && !this._subscribed) this._subscribe();
  }
  disconnectedCallback() {
    if (this._unsub) Promise.resolve(this._unsub).then((u) => typeof u === "function" && u()).catch(() => {});
    this._unsub = null;
    this._subscribed = false;
  }
  _subscribe() {
    this.disconnectedCallback();
    this._subscribed = true;
    const type = this._config.forecast_type === "hourly" ? "hourly" : "daily";
    this._unsub = subscribeForecast(this._hass, this._config.entity, type, (f) => {
      this._forecast = f;
      this._render();
    });
  }
  _render() {
    if (!this._hass || !this._config) return;
    const hass = this._hass;
    const l = lang(hass);
    const state = hass.states[this._config.entity];
    const a = state ? state.attributes : {};
    const hourly = this._config.forecast_type === "hourly";
    const cls = (this._config.theme === "ha" ? "" : "meteo") + (this._config.size === "large" || this._config.size === "xl" ? " " + this._config.size : "");
    let title = this._config.name || this._config.title;
    if (!title) {
      title = a.point_name || a.friendly_name || this._config.entity;
      if (a.point_name && a.elevation != null) title += `, ${fmt(a.elevation)} ${ASL[l] || ASL.en}`;
    }
    if (!state || state.state === "unavailable") {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card class="${cls}"><div class="title">${esc(title)}</div><div class="empty">${esc(L(hass, "unavailable"))}</div></ha-card>`;
      return;
    }
    const parts = [this._style(), `<ha-card class="${cls}"><div class="wrap">`];
    if (this._config.show_current) {
      const night = isNightAt(new Date(), hass);
      const conditionText = hass.localize ? hass.localize(`component.weather.entity_component._.state.${state.state}`) || state.state : state.state;
      const secondary = [];
      if (a.humidity != null) secondary.push(`${esc(L(hass, "humidity"))} ${fmt(a.humidity)} %`);
      if (a.wind_speed != null) secondary.push(`${esc(L(hass, "wind"))} ${fmt(a.wind_speed)} ${esc(a.wind_speed_unit || "km/h")}`);
      if (a.precipitation_probability != null) secondary.push(`${esc(L(hass, "rain_prob"))} ${fmt(a.precipitation_probability)} %`);
      parts.push(`<div class="current">
        <img class="big" src="${iconFor(a.symbol, state.state, night, this._config.animated)}" alt="${esc(state.state)}" />
        <div class="now">
          <div class="title">${esc(title)}</div>
          <div class="cond">${esc(conditionText)}</div>
          <div class="sec">${secondary.join(" · ")}</div>
        </div>
        <div class="temp">${fmt(a.temperature, 1)}<span class="unit">${esc(a.temperature_unit || "°C")}</span></div>
      </div>`);
    } else {
      parts.push(`<div class="title small">${esc(title)}</div>`);
    }
    if (this._config.show_forecast && this._forecast && this._forecast.length) {
      const wanted = Number(this._config.columns) || (hourly ? 8 : 7);
      const rows = this._forecast.slice(0, Math.max(3, Math.min(hourly ? 24 : 9, wanted)));
      const cells = rows.map((r, i) => {
        const d = new Date(r.datetime);
        if (hourly) {
          const label = d.toLocaleTimeString(l, { hour: "2-digit", minute: "2-digit" });
          const icon = iconFor(r.symbol, r.condition, isNightAt(d, hass), this._config.animated);
          const rain = r.precipitation != null && r.precipitation > 0 ? `<div class="rain">${fmt(r.precipitation, 1)} mm</div>` : `<div class="rain dry">${r.precipitation_probability != null ? fmt(r.precipitation_probability) + " %" : "–"}</div>`;
          return `<div class="col${d.getHours() === 0 && i > 0 ? " daybreak" : ""}"><div class="lbl">${esc(label)}</div><img src="${icon}" alt="" /><div class="t one">${fmt(r.temperature)}°</div>${rain}</div>`;
        }
        const label = i === 0 && d.toDateString() === new Date().toDateString() ? L(hass, "today") : d.toLocaleDateString(l, { weekday: "short" }).replace(/\.$/, "");
        const icon = iconFor(r.symbol, r.condition, false, this._config.animated);
        const rain = r.precipitation != null ? `<div class="rain${r.precipitation > 0 ? "" : " dry"}">${fmt(r.precipitation, 0)} mm</div>` : "";
        return `<div class="col"><div class="lbl">${esc(label)}</div><img src="${icon}" alt="" /><div class="t"><span class="lo">${fmt(r.templow)}°</span><span class="hi">${fmt(r.temperature)}°</span></div>${rain}</div>`;
      });
      parts.push(`<div class="row ${hourly ? "hourly" : "daily"}">${cells.join("")}</div>`);
    }
    parts.push("</div></ha-card>");
    this.shadowRoot.innerHTML = parts.join("");
    this.shadowRoot.querySelector(".current, .title")?.addEventListener("click", () => {
      const ev = new Event("hass-more-info", { bubbles: true, composed: true });
      ev.detail = { entityId: this._config.entity };
      this.dispatchEvent(ev);
    });
  }
  _style() {
    return `<style>
      :host { display: block; }
      ha-card { padding: 14px 16px 12px; overflow: hidden;
        --sm-text: var(--primary-text-color); --sm-dim: var(--secondary-text-color); --sm-panel: var(--secondary-background-color, rgba(128,128,128,0.08));
        --sm-box: rgba(128,128,128,0.18); --sm-rain: var(--swiss-meteo-rain, #4a90d9); }
      ha-card.meteo { background: #1c2733; color: #fff; --sm-text: #fff; --sm-dim: #c3ccd6; --sm-panel: #2b3a4b; --sm-box: #4a5f75; --sm-rain: #9fd0f5; }
      ha-card { --ico-big: 84px; --ico-row: 46px; --fs: 1; }
      ha-card.large { --ico-big: 112px; --ico-row: 64px; --fs: 1.22; }
      ha-card.xl { --ico-big: 144px; --ico-row: 84px; --fs: 1.45; }
      ha-card { display: block; container-type: inline-size; }
      @container (max-width: 300px) { .wrap { --ico-big: 64px; --ico-row: 40px; --fs: 0.9; } .current { grid-template-columns: var(--ico-big) minmax(0, 1fr); } .temp { grid-column: 1 / -1; justify-self: end; } }
      .empty { opacity: 0.7; padding: 8px 0; }
      .current { display: grid; grid-template-columns: var(--ico-big) minmax(0, 1fr) auto; gap: 12px; align-items: center; cursor: pointer; }
      .current .big { width: var(--ico-big); height: var(--ico-big); }
      .title { font-size: calc(1.25em * var(--fs)); font-weight: 700; line-height: 1.15; color: var(--sm-text); }
      .title.small { cursor: pointer; margin-bottom: 8px; }
      .cond { font-size: calc(0.95em * var(--fs)); margin-top: 2px; text-transform: capitalize; color: var(--sm-text); }
      .sec { font-size: calc(0.8em * var(--fs)); color: var(--sm-dim); margin-top: 2px; }
      .temp { font-size: calc(2.6em * var(--fs)); font-weight: 300; line-height: 1; color: var(--sm-text); white-space: nowrap; }
      .temp .unit { font-size: 0.45em; margin-left: 2px; vertical-align: top; }
      .row { display: flex; gap: 2px; margin-top: 12px; overflow-x: auto; scrollbar-width: thin; }
      ha-card.meteo .row { background: var(--sm-panel); border-radius: 4px; padding: 8px 4px; }
      .col { flex: 1 1 0; min-width: calc(54px * var(--fs)); text-align: center; padding: 2px 0; color: var(--sm-text); }
      .row.daily .col { min-width: calc(40px * var(--fs)); }
      .col.daybreak { border-left: 1px solid rgba(255,255,255,0.25); }
      ha-card:not(.meteo) .col.daybreak { border-left: 1px solid var(--divider-color, #666); }
      .col img { width: var(--ico-row); height: var(--ico-row); }
      .lbl { font-size: calc(0.8em * var(--fs)); color: var(--sm-dim); }
      .t { display: flex; flex-wrap: wrap; justify-content: center; gap: 3px; margin: 2px 0; }
      .t span { border-radius: 3px; padding: 3px 0; min-width: 2.2em; font-size: calc(0.9em * var(--fs)); }
      ha-card.meteo .t span { background: var(--sm-box); }
      ha-card:not(.meteo) .t .lo { opacity: 0.6; }
      ha-card:not(.meteo) .t .hi { font-weight: 500; }
      .t.one { font-size: calc(1.05em * var(--fs)); }
      .rain { font-size: calc(0.78em * var(--fs)); color: var(--sm-rain); }
      .rain.dry { color: var(--sm-dim); opacity: 0.8; }
    </style>`;
  }
}
customElements.define("swiss-meteo-forecast-card", SwissMeteoForecastCard);

class SwissMeteoForecastCardEditor extends SwissMeteoBaseEditor {}
SwissMeteoForecastCardEditor.defaults = { forecast_type: "daily", show_current: true, show_forecast: true, size: "normal", animated: true, theme: "meteo" };
SwissMeteoForecastCardEditor.schema = [
  { name: "entity", required: true, selector: { entity: { domain: "weather" } } },
  { name: "name", selector: { text: {} } },
  { name: "forecast_type", selector: { select: { mode: "dropdown", options: [{ value: "daily", label: "daily" }, { value: "hourly", label: "hourly" }] } } },
  { name: "columns", selector: { number: { min: 0, max: 24, mode: "box" } } },
  { name: "show_current", selector: { boolean: {} } },
  { name: "show_forecast", selector: { boolean: {} } },
  { name: "size", selector: { select: { mode: "dropdown", options: [{ value: "normal", label: "normal" }, { value: "large", label: "large" }, { value: "xl", label: "XL" }] } } },
  { name: "animated", selector: { boolean: {} } },
  { name: "theme", selector: { select: { mode: "dropdown", options: [{ value: "meteo", label: "Swiss Meteo" }, { value: "ha", label: "Home Assistant" }] } } },
];
customElements.define("swiss-meteo-forecast-card-editor", SwissMeteoForecastCardEditor);

window.customCards.push({
  type: "swiss-meteo-forecast-card",
  name: "Swiss Meteo – forecast",
  description: "The weather-forecast card in the MeteoSwiss look: current conditions and a row of days or hours.",
  preview: true,
});

/* ------------------------------------------------------------------------
 * Sky card — the glass panel of the Swiss Meteo banner: place and
 * condition, the big temperature with the symbol, a row of details and
 * a row of days or hours, on the blue sky gradient with the mountain
 * silhouette (or as the panel alone, for dashboards of your own).
 * ---------------------------------------------------------------------- */

const SKY_MOUNTAINS = "M0 170 L140 90 L230 140 L380 40 L520 150 L640 95 L760 160 L900 70 L1050 150 L1160 110 L1280 160 L1280 220 L0 220Z";

class SwissMeteoSkyCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._forecast = null;
    this._unsub = null;
    this._lastState = null;
  }
  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = { forecast_type: "daily", show_current: true, show_details: true, show_forecast: true, columns: 0, size: "normal", animated: true, background: "sky", theme: "meteo", ...config };
    this._subscribed = false;
    this._forecast = null;
    this._render();
  }
  static getConfigElement() {
    return document.createElement("swiss-meteo-sky-card-editor");
  }
  static getStubConfig(hass, entities) {
    const entity = (entities || []).find((e) => e.startsWith("weather.swiss_meteo")) || (entities || []).find((e) => e.startsWith("weather.")) || "";
    return { entity, forecast_type: "daily" };
  }
  getCardSize() {
    return (this._config.show_current ? 2 : 0) + (this._config.show_details ? 1 : 0) + (this._config.show_forecast ? 2 : 0);
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._subscribed && hass.connection && this._config) this._subscribe();
    const state = hass.states[this._config.entity];
    const stamp = state ? state.last_updated : "none";
    if (stamp !== this._lastState) {
      this._lastState = stamp;
      this._render();
    }
  }
  connectedCallback() {
    if (this._hass && !this._subscribed) this._subscribe();
  }
  disconnectedCallback() {
    if (this._unsub) Promise.resolve(this._unsub).then((u) => typeof u === "function" && u()).catch(() => {});
    this._unsub = null;
    this._subscribed = false;
  }
  _subscribe() {
    this.disconnectedCallback();
    this._subscribed = true;
    const type = this._config.forecast_type === "hourly" ? "hourly" : "daily";
    this._unsub = subscribeForecast(this._hass, this._config.entity, type, (f) => {
      this._forecast = f;
      this._render();
    });
  }
  _render() {
    if (!this._hass || !this._config) return;
    const hass = this._hass;
    const l = lang(hass);
    const state = hass.states[this._config.entity];
    const a = state ? state.attributes : {};
    const hourly = this._config.forecast_type === "hourly";
    const cls = (this._config.background === "panel" ? "panel" : "sky") + (this._config.theme === "sky" ? " blue" : "") + (this._config.size === "large" || this._config.size === "xl" ? " " + this._config.size : "");
    const name = this._config.name || this._config.title || a.point_name || a.friendly_name || this._config.entity;
    const sky = cls === "sky" ? `<svg class="mtn" viewBox="0 0 1280 220" preserveAspectRatio="none"><path d="${SKY_MOUNTAINS}" /></svg>` : "";
    if (!state || state.state === "unavailable") {
      this.shadowRoot.innerHTML = `${this._style()}<ha-card class="${cls}">${sky}<div class="glass"><div class="loc">${esc(name)}</div><div class="cond">${esc(L(hass, "unavailable"))}</div></div></ha-card>`;
      return;
    }
    const parts = [this._style(), `<ha-card class="${cls}">${sky}<div class="glass">`];
    if (this._config.show_current) {
      const night = isNightAt(new Date(), hass);
      const conditionText = hass.localize ? hass.localize(`component.weather.entity_component._.state.${state.state}`) || state.state : state.state;
      parts.push(`<div class="top">
        <div class="who"><div class="loc">${esc(name)}</div><div class="cond">${esc(conditionText)}</div></div>
        <div class="big"><img src="${iconFor(a.symbol, state.state, night, this._config.animated)}" alt="${esc(state.state)}" /><div class="tmp">${fmt(a.temperature)}°</div></div>
      </div>`);
    } else {
      parts.push(`<div class="top"><div class="who"><div class="loc">${esc(name)}</div></div></div>`);
    }
    if (this._config.show_details) {
      const det = [];
      if (a.humidity != null) det.push(["humidity", `${fmt(a.humidity)} %`]);
      if (a.wind_speed != null) det.push(["wind", `${fmt(a.wind_speed)} ${esc(a.wind_speed_unit || "km/h")} ${bearingArrow(a.wind_bearing)}`]);
      const next = this._forecast && this._forecast.length ? this._forecast[0] : null;
      if (next && next.precipitation != null) det.push(["raindrops", `${fmt(next.precipitation, 1)} mm`]);
      else if (a.precipitation_probability != null) det.push(["umbrella", `${fmt(a.precipitation_probability)} %`]);
      if (det.length) parts.push(`<div class="det">${det.map(([ic, v]) => `<span><img src="${iconUrl(ic, this._config.animated)}" alt="" />${v}</span>`).join("")}</div>`);
    }
    if (this._config.show_forecast && this._forecast && this._forecast.length) {
      const wanted = Number(this._config.columns) || (hourly ? 6 : 5);
      const rows = this._forecast.slice(0, Math.max(3, Math.min(hourly ? 24 : 9, wanted)));
      const cells = rows.map((r, i) => {
        const d = new Date(r.datetime);
        if (hourly) {
          const label = d.toLocaleTimeString(l, { hour: "2-digit", minute: "2-digit" });
          const icon = iconFor(r.symbol, r.condition, isNightAt(d, hass), this._config.animated);
          const sub = r.precipitation != null && r.precipitation > 0 ? `${fmt(r.precipitation, 1)} mm` : r.precipitation_probability != null ? `${fmt(r.precipitation_probability)} %` : "";
          return `<div class="d"><div class="dn">${esc(label)}</div><img src="${icon}" alt="" /><div class="hi">${fmt(r.temperature)}°</div><div class="lo">${esc(sub)}</div></div>`;
        }
        const label = i === 0 && d.toDateString() === new Date().toDateString() ? L(hass, "today") : d.toLocaleDateString(l, { weekday: "short" }).replace(/\.$/, "");
        const icon = iconFor(r.symbol, r.condition, false, this._config.animated);
        return `<div class="d"><div class="dn">${esc(label)}</div><img src="${icon}" alt="" /><div class="hi">${fmt(r.temperature)}°</div><div class="lo">${fmt(r.templow)}°</div></div>`;
      });
      parts.push(`<div class="fc">${cells.join("")}</div>`);
    }
    parts.push("</div></ha-card>");
    this.shadowRoot.innerHTML = parts.join("");
    this.shadowRoot.querySelector(".top")?.addEventListener("click", () => {
      const ev = new Event("hass-more-info", { bubbles: true, composed: true });
      ev.detail = { entityId: this._config.entity };
      this.dispatchEvent(ev);
    });
  }
  _style() {
    return `<style>
      :host { display: block; }
      ha-card { position: relative; overflow: hidden; color: #fff; border: none; --ico-big: 96px; --ico-row: 48px; --fs: 1; }
      ha-card.large { --ico-big: 124px; --ico-row: 64px; --fs: 1.22; }
      ha-card.xl { --ico-big: 156px; --ico-row: 84px; --fs: 1.45; }
      ha-card { --sk-bg: linear-gradient(160deg, #27384a 0%, #1c2733 100%); --sk-mtn: #121a23; --sk-glass: rgba(43,58,75,0.92); --sk-border: rgba(195,204,214,0.18);
        --sk-text: #fff; --sk-dim: #c3ccd6; --sk-line: rgba(195,204,214,0.2); }
      ha-card.blue { --sk-bg: radial-gradient(ellipse at 78% 18%, #2a8ae0 0%, rgba(42,138,224,0) 55%), linear-gradient(160deg, #0d4a86 0%, #082a4e 100%); --sk-mtn: #06223f;
        --sk-glass: rgba(10,30,56,0.86); --sk-border: rgba(143,195,240,0.25); --sk-text: #fff; --sk-dim: #8fc3f0; --sk-line: rgba(143,195,240,0.2); }
      ha-card.sky { padding: 18px 20px; background: var(--sk-bg); }
      ha-card { display: block; container-type: inline-size; }
      @container (max-width: 300px) { .glass { --ico-big: 72px; --ico-row: 36px; --fs: 0.9; padding: 12px 12px 10px; } }
      ha-card.panel { padding: 0; background: var(--sk-glass); border: 1px solid var(--sk-border); }
      .mtn { position: absolute; left: 0; right: 0; bottom: 0; width: 100%; height: 34%; }
      .mtn path { fill: var(--sk-mtn); opacity: 0.7; }
      .glass { position: relative; padding: 16px 18px 14px; border-radius: 16px; }
      ha-card.sky .glass { background: var(--sk-glass); border: 1px solid var(--sk-border); box-shadow: 0 12px 30px rgba(0,0,0,0.35); }
      .top { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 4px 8px; cursor: pointer; }
      .who { min-width: 0; flex: 1 1 120px; }
      .loc { font-size: calc(1.45em * var(--fs)); color: var(--sk-text); line-height: 1.2; font-weight: 500; }
      ha-card.blue .loc { color: #bfdcf7; }
      .cond { font-size: calc(1.08em * var(--fs)); color: var(--sk-dim); margin-top: 3px; text-transform: capitalize; }
      .big { display: flex; align-items: center; gap: 2px; flex: 0 0 auto; margin-left: auto; margin-right: 4px; }
      .big img { width: var(--ico-big); height: var(--ico-big); margin: calc(var(--ico-big) * -0.12) calc(var(--ico-big) * -0.06) calc(var(--ico-big) * -0.12) 0; }
      .tmp { font-size: calc(3.3em * var(--fs)); font-weight: 700; line-height: 1; letter-spacing: -1px; white-space: nowrap; margin-left: 8px; }
      .det { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 10px 0 12px; font-size: calc(1em * var(--fs)); color: var(--sk-dim); }
      ha-card.blue .det { color: #bfdcf7; }
      .det span { display: inline-flex; align-items: center; gap: 2px; }
      .det img { width: calc(30px * var(--fs)); height: calc(30px * var(--fs)); margin: -3px 0; }
      .fc { display: flex; justify-content: space-between; border-top: 1px solid var(--sk-line); padding-top: 12px; overflow-x: auto; gap: 0; scrollbar-width: thin; }
      .d { flex: 1 1 0; min-width: calc(var(--ico-row) * 0.95); text-align: center; }
      .dn { font-size: calc(0.95em * var(--fs)); color: var(--sk-dim); margin-bottom: 0; white-space: nowrap; }
      .d img { width: var(--ico-row); height: var(--ico-row); margin: calc(var(--ico-row) * -0.08) 0; }
      .hi { font-size: calc(1.2em * var(--fs)); font-weight: 700; margin-top: 0; }
      .lo { font-size: calc(0.95em * var(--fs)); color: var(--sk-dim); white-space: nowrap; }
    </style>`;
  }
}
customElements.define("swiss-meteo-sky-card", SwissMeteoSkyCard);

class SwissMeteoSkyCardEditor extends SwissMeteoBaseEditor {}
SwissMeteoSkyCardEditor.defaults = { forecast_type: "daily", show_current: true, show_details: true, show_forecast: true, size: "normal", animated: true, background: "sky", theme: "meteo" };
SwissMeteoSkyCardEditor.schema = [
  { name: "entity", required: true, selector: { entity: { domain: "weather" } } },
  { name: "name", selector: { text: {} } },
  { name: "forecast_type", selector: { select: { mode: "dropdown", options: [{ value: "daily", label: "daily" }, { value: "hourly", label: "hourly" }] } } },
  { name: "columns", selector: { number: { min: 0, max: 24, mode: "box" } } },
  { name: "show_current", selector: { boolean: {} } },
  { name: "show_details", selector: { boolean: {} } },
  { name: "show_forecast", selector: { boolean: {} } },
  { name: "size", selector: { select: { mode: "dropdown", options: [{ value: "normal", label: "normal" }, { value: "large", label: "large" }, { value: "xl", label: "XL" }] } } },
  { name: "animated", selector: { boolean: {} } },
  { name: "background", selector: { select: { mode: "dropdown", options: [{ value: "sky", label: "Sky" }, { value: "panel", label: "Panel" }] } } },
  { name: "theme", selector: { select: { mode: "dropdown", options: [{ value: "meteo", label: "Swiss Meteo" }, { value: "sky", label: "Banner blue" }] } } },
];
customElements.define("swiss-meteo-sky-card-editor", SwissMeteoSkyCardEditor);

window.customCards.push({
  type: "swiss-meteo-sky-card",
  name: "Swiss Meteo – sky",
  description: "Glass panel on a sky with mountains: current conditions, details and a row of days or hours.",
  preview: true,
});

console.info(`%c SWISS-METEO-CARD %c ${CARD_VERSION} `, "color: white; background: #c8102e; font-weight: 700;", "color: #c8102e; background: white; font-weight: 700;");
