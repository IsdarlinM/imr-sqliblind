"use strict";

const scanMenuState = {
  mode: "custom",
  savedProfile: null,
  defaultDraft: null,
  customDraft: null,
  dirty: false,
  initialized: false,
  lastPanel: "sessions",
};

function cloneScanProfile(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function scanProfileFieldValue(name, value) {
  if (name === "headers") {
    return Object.entries(value || {})
      .map(([key, item]) => `${key}: ${item}`)
      .join("\n");
  }
  if (name === "cookies") {
    return Object.entries(value || {})
      .map(([key, item]) => `${key}=${item}`)
      .join("\n");
  }
  if (name === "true_statuses" || name === "data_tables") {
    return Array.isArray(value) ? value.join(", ") : value || "";
  }
  return value ?? "";
}

function fillScanForm(profile) {
  const form = $("scanForm");
  for (const field of form.elements) {
    if (!field.name || !(field.name in profile)) {
      continue;
    }
    const value = profile[field.name];
    if (field.type === "checkbox") {
      field.checked = Boolean(value);
      continue;
    }
    field.value = String(scanProfileFieldValue(field.name, value));
  }
  scanMenuState.dirty = false;
  updateScanMenuMode();
}

function captureScanDraft() {
  const form = $("scanForm");
  if (!form || !scanMenuState.initialized) {
    return;
  }
  const payload = formPayload(form);
  if (scanMenuState.mode === "defaults") {
    scanMenuState.defaultDraft = cloneScanProfile(payload);
  } else if (scanMenuState.mode === "custom") {
    scanMenuState.customDraft = cloneScanProfile(payload);
  }
}

function menuElement(name, className, text) {
  const element = document.createElement(name);
  if (className) {
    element.className = className;
  }
  if (text !== undefined) {
    element.textContent = text;
  }
  return element;
}

function closeAppMenu() {
  const menu = $("appMenu");
  const backdrop = $("appMenuBackdrop");
  const toggle = $("appMenuToggle");
  menu?.classList.remove("open");
  menu?.setAttribute("aria-hidden", "true");
  if (backdrop) {
    backdrop.hidden = true;
  }
  if (toggle) {
    toggle.setAttribute("aria-expanded", "false");
  }
  document.body.classList.remove("web-menu-open");
}

function openAppMenu(panel = scanMenuState.lastPanel) {
  switchScanMenuPanel(panel);
  const menu = $("appMenu");
  const backdrop = $("appMenuBackdrop");
  const toggle = $("appMenuToggle");
  menu?.classList.add("open");
  menu?.setAttribute("aria-hidden", "false");
  if (backdrop) {
    backdrop.hidden = false;
  }
  if (toggle) {
    toggle.setAttribute("aria-expanded", "true");
  }
  document.body.classList.add("web-menu-open");
  requestAnimationFrame(() => {
    menu?.querySelector("[data-menu-nav].active")?.focus();
  });
}

function updateScanMenuMode() {
  const defaults = scanMenuState.mode === "defaults";
  const title = $("scanMenuTitle");
  const description = $("scanMenuDescription");
  const status = $("scanProfileStatus");
  const save = $("saveDefaultScan");
  const run = $("runCustomScan");
  const restore = $("restoreScanProfile");

  if (title) {
    title.textContent = defaults
      ? "Default scan configuration"
      : "Custom scan";
  }
  if (description) {
    description.textContent = defaults
      ? "Saved values are loaded into every new custom scan. Saving is always explicit."
      : "This scan starts from the saved defaults. Your changes are temporary and will not update them.";
  }
  if (status) {
    status.textContent = scanMenuState.dirty
      ? defaults
        ? "Unsaved default changes"
        : "Temporary custom changes"
      : defaults
        ? "Saved profile loaded"
        : "Defaults copied · not persisted";
    status.classList.toggle("dirty", scanMenuState.dirty);
  }
  if (save) {
    save.hidden = !defaults;
  }
  if (run) {
    run.hidden = defaults;
  }
  if (restore) {
    restore.textContent = defaults
      ? "Restore saved configuration"
      : "Reload saved defaults";
  }
}

function switchScanMenuPanel(panel) {
  captureScanDraft();
  scanMenuState.lastPanel = panel;

  document.querySelectorAll("[data-menu-nav]").forEach((button) => {
    const active = button.dataset.menuNav === panel;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });

  const sessions = $("sessionMenuPanel");
  const configuration = $("scanMenuPanel");
  const isSessions = panel === "sessions";
  if (sessions) {
    sessions.hidden = !isSessions;
  }
  if (configuration) {
    configuration.hidden = isSessions;
  }
  if (isSessions) {
    return;
  }

  scanMenuState.mode = panel === "defaults" ? "defaults" : "custom";
  const profile =
    scanMenuState.mode === "defaults"
      ? scanMenuState.defaultDraft || scanMenuState.savedProfile
      : scanMenuState.customDraft || scanMenuState.savedProfile;
  if (profile) {
    fillScanForm(profile);
  }
  updateScanMenuMode();
}

async function loadSavedScanProfile() {
  const response = await api("/api/settings/default-scan");
  const result = await response.json();
  scanMenuState.savedProfile = cloneScanProfile(result.config);
  scanMenuState.defaultDraft = cloneScanProfile(result.config);
  scanMenuState.customDraft = cloneScanProfile(result.config);
  scanMenuState.initialized = true;
  fillScanForm(scanMenuState.customDraft);

  const meta = $("savedProfileMeta");
  if (meta) {
    meta.textContent = result.saved
      ? `Saved ${result.updated_at || "locally"}`
      : "Using built-in defaults until you save a profile.";
  }
}

async function saveDefaultScanProfile() {
  const form = $("scanForm");
  const response = await api("/api/settings/default-scan", {
    method: "PUT",
    body: JSON.stringify(formPayload(form)),
  });
  const result = await response.json();
  scanMenuState.savedProfile = cloneScanProfile(result.config);
  scanMenuState.defaultDraft = cloneScanProfile(result.config);
  scanMenuState.customDraft = cloneScanProfile(result.config);
  scanMenuState.dirty = false;
  const meta = $("savedProfileMeta");
  if (meta) {
    meta.textContent = `Saved ${result.updated_at || "now"}`;
  }
  updateScanMenuMode();
  toast("Default scan configuration saved.");
}

async function runTemporaryCustomScan() {
  const form = $("scanForm");
  const response = await api("/api/scans", {
    method: "POST",
    body: JSON.stringify(formPayload(form)),
  });
  const result = await response.json();
  scanMenuState.customDraft = cloneScanProfile(scanMenuState.savedProfile);
  scanMenuState.dirty = false;
  closeAppMenu();
  await selectScan(result.id);
  toast("Custom scan started. Defaults were not changed.");
}

function restoreCurrentScanProfile() {
  const profile =
    scanMenuState.mode === "defaults"
      ? scanMenuState.savedProfile
      : scanMenuState.savedProfile;
  if (!profile) {
    return;
  }
  if (scanMenuState.mode === "defaults") {
    scanMenuState.defaultDraft = cloneScanProfile(profile);
  } else {
    scanMenuState.customDraft = cloneScanProfile(profile);
  }
  fillScanForm(profile);
  toast("Saved defaults restored.");
}

function buildScanMenu() {
  const sidebar = document.querySelector(".sidebar");
  const topbar = document.querySelector(".topbar");
  const form = $("scanForm");
  if (!sidebar || !topbar || !form) {
    return;
  }

  const panels = [...sidebar.children].filter((node) =>
    node.classList?.contains("panel"),
  );
  const configuration = panels[0];
  const sessions = panels[1];
  if (!configuration || !sessions) {
    return;
  }

  sidebar.id = "appMenu";
  sidebar.classList.add("app-menu");
  sidebar.setAttribute("aria-hidden", "true");
  sidebar.setAttribute("aria-label", "Application menu");

  configuration.id = "scanMenuPanel";
  configuration.classList.add("app-menu-panel");
  sessions.id = "sessionMenuPanel";
  sessions.classList.add("app-menu-panel");

  const menuHeader = menuElement("div", "app-menu-header");
  const heading = menuElement("div", "app-menu-heading");
  heading.append(
    menuElement("strong", "", "imr-sqliblind"),
    menuElement("span", "muted", "Scan workspace"),
  );
  const close = menuElement("button", "app-menu-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Close menu");
  close.addEventListener("click", closeAppMenu);
  menuHeader.append(heading, close);

  const navigation = menuElement("nav", "app-menu-navigation");
  navigation.setAttribute("aria-label", "Web console menu");
  for (const [name, label] of [
    ["sessions", "Sessions"],
    ["defaults", "Default configuration"],
    ["custom", "Custom scan"],
  ]) {
    const button = menuElement("button", "", label);
    button.type = "button";
    button.dataset.menuNav = name;
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => switchScanMenuPanel(name));
    navigation.append(button);
  }

  sidebar.prepend(menuHeader, navigation);

  const originalTitle = configuration.querySelector("h1");
  if (originalTitle) {
    originalTitle.id = "scanMenuTitle";
    originalTitle.textContent = "Custom scan";
    const description = menuElement("p", "", "");
    description.id = "scanMenuDescription";
    originalTitle.after(description);
  }

  const statusWrap = menuElement("div", "scan-profile-summary");
  const status = menuElement("span", "scan-profile-status", "");
  status.id = "scanProfileStatus";
  const meta = menuElement("small", "muted", "Loading saved defaults…");
  meta.id = "savedProfileMeta";
  statusWrap.append(status, meta);
  form.prepend(statusWrap);

  const security = menuElement(
    "p",
    "scan-profile-security",
    "Security: cookies, proxy credentials, sensitive headers and revealed sensitive values are never saved as defaults.",
  );

  const submit = form.querySelector('button.primary[type="submit"]');
  const actions = menuElement("div", "scan-menu-actions");
  const restore = menuElement("button", "", "Reload saved defaults");
  restore.id = "restoreScanProfile";
  restore.type = "button";
  restore.addEventListener("click", restoreCurrentScanProfile);
  const save = menuElement("button", "primary", "Save default configuration");
  save.id = "saveDefaultScan";
  save.type = "button";
  save.addEventListener("click", () => {
    saveDefaultScanProfile().catch((error) => toast(error.message));
  });
  if (submit) {
    submit.id = "runCustomScan";
    submit.textContent = "Run custom scan";
    submit.remove();
  }
  actions.append(restore, save);
  if (submit) {
    actions.append(submit);
  }
  form.append(security, actions);

  const toggle = menuElement("button", "app-menu-toggle", "☰");
  toggle.id = "appMenuToggle";
  toggle.type = "button";
  toggle.setAttribute("aria-label", "Open menu");
  toggle.setAttribute("aria-controls", "appMenu");
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    if (sidebar.classList.contains("open")) {
      closeAppMenu();
    } else {
      openAppMenu();
    }
  });
  topbar.prepend(toggle);

  const backdrop = menuElement("div", "app-menu-backdrop");
  backdrop.id = "appMenuBackdrop";
  backdrop.hidden = true;
  backdrop.addEventListener("click", closeAppMenu);
  document.body.append(backdrop);

  form.addEventListener(
    "submit",
    (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      const action =
        scanMenuState.mode === "defaults"
          ? saveDefaultScanProfile()
          : runTemporaryCustomScan();
      action.catch((error) => toast(error.message));
    },
    true,
  );

  form.addEventListener("input", () => {
    if (!scanMenuState.initialized) {
      return;
    }
    scanMenuState.dirty = true;
    updateScanMenuMode();
  });

  $("sessions")?.addEventListener("click", (event) => {
    if (event.target.closest?.(".session")) {
      closeAppMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar.classList.contains("open")) {
      closeAppMenu();
      toggle.focus();
    }
  });

  switchScanMenuPanel("sessions");
}

buildScanMenu();
loadSavedScanProfile().catch((error) => {
  scanMenuState.initialized = true;
  toast(`Could not load defaults: ${error.message}`);
});
