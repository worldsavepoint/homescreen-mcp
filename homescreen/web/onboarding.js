/* Language controls, host setup entry and per-session browser consent. */
(() => {
  "use strict";
  const i18n = window.ScreenOrganizerI18n;
  const host = window.screenOrganizerHost;
  const native = host?.native === true;
  const $ = selector => document.querySelector(selector);
  const send = message => window.webkit?.messageHandlers?.screenOrganizer?.postMessage(message);
  let accepted = native && host.consentAccepted === true;
  let reachedEnd = false, declined = false, returnFocus = null;
  let resolveConsent;
  const consent = new Promise(resolve => { resolveConsent = resolve; });
  if (accepted) resolveConsent();

  function backgroundInert(value) {
    for (const node of document.querySelectorAll("header,main,footer,#selection-bar,#drawer")) node.inert = value;
  }
  function updateConsent() {
    const text = $("#consent-text");
    if (text.scrollTop + text.clientHeight >= text.scrollHeight - 2) reachedEnd = true;
    $("#consent-continue").disabled = declined || !reachedEnd || !$("#consent-agree").checked;
  }
  function languageOptions() {
    for (const selector of ["#language-select", "#consent-language-select"]) {
      const select = $(selector);
      select.replaceChildren();
      for (const language of [{code: "system", name: i18n.t("common.system")}, ...i18n.languages]) {
        const option = document.createElement("option");
        option.value = language.code;
        option.textContent = language.name;
        select.appendChild(option);
      }
      select.value = i18n.preference;
    }
  }
  function onLocale() {
    languageOptions();
    document.title = i18n.t("app.name") + " · " + i18n.t("app.subtitle");
    // A newly translated agreement must be read in its displayed language.
    if (!accepted) {
      reachedEnd = false;
      $("#consent-text").scrollTop = 0;
      requestAnimationFrame(updateConsent);
    }
  }
  function hideSetup() {
    $("#mcp-dialog").hidden = true;
    backgroundInert(false);
    returnFocus?.focus();
  }
  const serverID = "ios-homescreen-mcp";
  const entry = {command: "home-screen-mcp", args: [], env: {HOMESCREEN_READ_ONLY: "1"}};
  const examples = [
    ["codex", "Codex CLI", `codex mcp add ${serverID} --env HOMESCREEN_READ_ONLY=1 -- home-screen-mcp`],
    ["claude", "Claude Code CLI", `claude mcp add --env HOMESCREEN_READ_ONLY=1 --transport stdio ${serverID} -- home-screen-mcp`],
    ["json", "mcp.copyJSON", JSON.stringify({mcpServers: {[serverID]: entry}}, null, 2)],
    ["toml", "mcp.copyCodex", `[mcp_servers.${serverID}]\ncommand = "home-screen-mcp"\nargs = []\n\n[mcp_servers.${serverID}.env]\nHOMESCREEN_READ_ONLY = "1"`],
    ["vscode", "mcp.copyVSCode", JSON.stringify({servers: {[serverID]: {type:"stdio", ...entry}}}, null, 2)],
  ];
  function setupExamples() {
    const root = $("#mcp-examples");
    for (const [id, label, text] of examples) {
      const section = document.createElement("section");
      const pre = document.createElement("pre");
      pre.tabIndex = 0;
      pre.textContent = text;
      const button = document.createElement("button");
      button.id = "mcp-copy-" + id;
      if (label.startsWith("mcp.")) button.setAttribute("data-i18n", label);
      else {
        button.textContent = i18n.t("common.copy") + " · " + label;
        i18n.onChange(() => { button.textContent = i18n.t("common.copy") + " · " + label; });
      }
      button.onclick = async () => {
        try {
          await navigator.clipboard.writeText(text);
          $("#mcp-copy-status").setAttribute("data-i18n", "common.copied");
          i18n.translateDOM($("#mcp-copy-status"));
        } catch (_) {
          $("#mcp-copy-status").setAttribute("data-i18n", "mcp.copyFailed");
          i18n.translateDOM($("#mcp-copy-status"));
          pre.focus();
        }
      };
      section.append(pre, button);
      root.appendChild(section);
    }
    i18n.translateDOM(root);
  }
  $("#mcp-setup").onclick = () => {
    if (!accepted) return;
    if (native) { send({action: "openMCPSetup"}); return; }
    returnFocus = document.activeElement;
    $("#mcp-copy-status").removeAttribute("data-i18n");
    $("#mcp-copy-status").textContent = "";
    $("#mcp-dialog").hidden = false;
    backgroundInert(true);
    $("#mcp-title").focus();
    $("#mcp-dialog .modal-card").scrollTop = 0;
  };
  $("#mcp-close").onclick = hideSetup;
  for (const selector of ["#language-select", "#consent-language-select"]) $(selector).onchange = async event => {
    await i18n.setLocale(event.target.value);
    if (native) send({action: "setLanguage", preference: i18n.preference});
  };
  $("#consent-text").addEventListener("scroll", updateConsent);
  $("#consent-agree").onchange = updateConsent;
  $("#consent-continue").onclick = () => {
    updateConsent();
    if ($("#consent-continue").disabled || accepted) return;
    accepted = true;
    $("#consent-dialog").hidden = true;
    backgroundInert(false);
    resolveConsent();
    window.dispatchEvent(new CustomEvent("screen-organizer-consent-accepted"));
    $("#read").focus();
  };
  $("#consent-decline").onclick = () => {
    declined = true;
    updateConsent();
    $("#consent-declined").hidden = false;
    // Browsers may refuse to close a tab they did not open. Keep its gate closed.
    window.close();
  };
  document.addEventListener("keydown", event => {
    const dialog = !$("#consent-dialog").hidden ? $("#consent-dialog") : !$("#mcp-dialog").hidden ? $("#mcp-dialog") : null;
    if (!dialog) return;
    if (event.key === "Escape") { event.preventDefault(); if (accepted) hideSetup(); }
    if (event.key === "Tab") {
      const controls = [...dialog.querySelectorAll("button,input,select,[tabindex]")].filter(n => !n.disabled && n.getAttribute("tabindex") !== "-1");
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement === $("#mcp-title"))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  const ready = (async () => {
    await i18n.ready;
    if (native && typeof host.languagePreference === "string") await i18n.setLocale(host.languagePreference);
    setupExamples();
    for (const id of ["consent-brand", "mcp-brand"]) $("#" + id).appendChild($(".brand svg").cloneNode(true));
    onLocale();
    backgroundInert(!accepted);
    i18n.onChange(onLocale);
    if (!accepted) {
      backgroundInert(true);
      $("#consent-dialog").hidden = false;
      $("#consent-text").focus();
      requestAnimationFrame(updateConsent);
    }
    await consent;
  })();
  window.ScreenOrganizerOnboarding = {ready, get accepted() { return accepted; }};
})();
