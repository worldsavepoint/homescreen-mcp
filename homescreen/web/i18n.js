/* Manifest-driven language selection, translation and formatting. */
(() => {
  "use strict";
  const storageKey = "screenOrganizer.language";
  const base = typeof document !== "undefined" && document.currentScript?.src
    ? new URL("locales/", document.currentScript.src).href : "/static/locales/";
  let manifest, english = {}, catalog = {}, locale = "en", preference = "system", revision = 0;
  const listeners = new Set(), catalogs = new Map();
  try { preference = localStorage.getItem(storageKey) || "system"; } catch (_) { /* storage unavailable */ }

  function canonical(value) {
    try { return Intl.getCanonicalLocales(String(value).replace(/_/g, "-"))[0] || ""; }
    catch (_) { return ""; }
  }

  function match(value) {
    const code = canonical(value);
    if (!code) return null;
    const parts = code.split("-");
    // Explicit Chinese scripts take precedence over a conflicting region alias.
    const script = parts.find(part => /^(Hans|Hant)$/.test(part));
    const candidates = script ? [parts[0] + "-" + script, code] : [code];
    for (let length = parts.length - 1; length > 0; length--) candidates.push(parts.slice(0, length).join("-"));
    for (const candidate of candidates) {
      const language = manifest.languages.find(item => item.code === candidate ||
        item.aliases.some(alias => canonical(alias) === candidate));
      if (language) return language.code;
    }
    return null;
  }

  function resolveLocale(request, preferredLanguages = globalThis.navigator?.languages || []) {
    if (request !== "system") return match(request) || manifest.default;
    for (const language of preferredLanguages) {
      const resolved = match(language);
      if (resolved) return resolved;
    }
    return manifest.default;
  }

  async function loadJSON(file) {
    const response = await fetch(base + file, { credentials: "same-origin" });
    if (!response.ok) throw new Error("Could not load translations: " + file);
    return response.json();
  }

  function loadCatalog(code) {
    if (!catalogs.has(code)) catalogs.set(code, loadJSON(code + ".json"));
    return catalogs.get(code);
  }

  function t(key, parameters = {}) {
    const text = Object.hasOwn(catalog, key) ? catalog[key] : english[key];
    if (typeof text !== "string") return key;
    return text.replace(/\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (token, name) =>
      Object.hasOwn(parameters, name) ? String(parameters[name]) : token);
  }

  function translateDOM(root = document) {
    const attributes = {"data-i18n": null, "data-i18n-title": "title",
      "data-i18n-placeholder": "placeholder", "data-i18n-aria-label": "aria-label"};
    const selector = Object.keys(attributes).map(name => "[" + name + "]").join(",");
    const nodes = [...(root.matches?.(selector) ? [root] : []), ...root.querySelectorAll(selector)];
    for (const node of nodes) for (const [source, target] of Object.entries(attributes)) {
      const key = node.getAttribute(source);
      if (key === null) continue;
      if (target) node.setAttribute(target, t(key));
      else node.textContent = t(key);
    }
  }

  async function select(request) {
    const current = ++revision;
    const nextPreference = request === "system" || manifest.languages.some(item => item.code === request)
      ? request : "system";
    const nextLocale = resolveLocale(nextPreference);
    let nextCatalog;
    try { nextCatalog = await loadCatalog(nextLocale); }
    catch (error) {
      if (nextLocale === manifest.default) throw error;
      catalogs.delete(nextLocale);
      nextCatalog = english;
    }
    if (current !== revision) return locale;
    preference = nextPreference;
    locale = nextLocale;
    catalog = nextCatalog;
    try { localStorage.setItem(storageKey, preference); } catch (_) { /* storage unavailable */ }
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
      translateDOM(document);
    }
    for (const listener of listeners) listener(locale);
    return locale;
  }

  const api = {
    get locale() { return locale; },
    get preference() { return preference; },
    get languages() { return manifest ? manifest.languages : []; },
    t, resolveLocale, translateDOM,
    async setLocale(request) { await api.ready; return select(request); },
    formatNumber(value) { return new Intl.NumberFormat(locale).format(value); },
    formatDate(value) { return new Intl.DateTimeFormat(locale).format(value); },
    onChange(listener) { listeners.add(listener); return () => listeners.delete(listener); },
  };
  globalThis.ScreenOrganizerI18n = api;
  api.ready = (async () => {
    manifest = await loadJSON("manifest.json");
    english = await loadCatalog(manifest.default);
    await select(preference);
  })();
  globalThis.addEventListener?.("languagechange", () => {
    if (preference === "system") api.setLocale("system");
  });
})();
