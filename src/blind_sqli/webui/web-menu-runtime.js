"use strict";

scanMenuState.busy = false;
const scanMenu = $("appMenu");

function syncScanMenuInertState() {
  if (scanMenu) {
    scanMenu.inert = !scanMenu.classList.contains("open");
  }
}

if (scanMenu) {
  document.body.classList.add("web-menu-ready");
  syncScanMenuInertState();
  if ("MutationObserver" in window) {
    new MutationObserver(syncScanMenuInertState).observe(scanMenu, {
      attributes: true,
      attributeFilter: ["class"],
    });
  }
}

function setScanMenuBusy(busy) {
  scanMenuState.busy = busy;
  for (const id of [
    "saveDefaultScan",
    "runCustomScan",
    "restoreScanProfile",
  ]) {
    const button = $(id);
    if (button) {
      button.disabled = busy;
    }
  }
}

const saveDefaultScanProfileBeforeReset = saveDefaultScanProfile;
saveDefaultScanProfile = async function saveDefaultScanProfileAndReset() {
  if (scanMenuState.busy) {
    return;
  }
  setScanMenuBusy(true);
  try {
    await saveDefaultScanProfileBeforeReset();
    if (scanMenuState.savedProfile) {
      fillScanForm(scanMenuState.savedProfile);
    }
  } finally {
    setScanMenuBusy(false);
  }
};

const runTemporaryCustomScanBeforeReset = runTemporaryCustomScan;
runTemporaryCustomScan = async function runTemporaryCustomScanAndReset() {
  if (scanMenuState.busy) {
    return;
  }
  setScanMenuBusy(true);
  try {
    await runTemporaryCustomScanBeforeReset();
    if (scanMenuState.savedProfile) {
      scanMenuState.customDraft = cloneScanProfile(scanMenuState.savedProfile);
      fillScanForm(scanMenuState.savedProfile);
    }
  } finally {
    setScanMenuBusy(false);
  }
};
