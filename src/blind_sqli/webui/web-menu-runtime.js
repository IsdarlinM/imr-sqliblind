"use strict";

const saveDefaultScanProfileBeforeReset = saveDefaultScanProfile;
saveDefaultScanProfile = async function saveDefaultScanProfileAndReset() {
  await saveDefaultScanProfileBeforeReset();
  if (scanMenuState.savedProfile) {
    fillScanForm(scanMenuState.savedProfile);
  }
};

const runTemporaryCustomScanBeforeReset = runTemporaryCustomScan;
runTemporaryCustomScan = async function runTemporaryCustomScanAndReset() {
  await runTemporaryCustomScanBeforeReset();
  if (scanMenuState.savedProfile) {
    scanMenuState.customDraft = cloneScanProfile(scanMenuState.savedProfile);
    fillScanForm(scanMenuState.savedProfile);
  }
};
