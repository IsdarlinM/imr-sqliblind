# Web console menu and scan profiles

The web console uses a hamburger menu so the result workspace can use the full browser width.

## Sessions

Open **Menu → Sessions** to select a previous or active scan. Selecting a session closes the menu and opens its current workspace, activity, entities and graph.

## Default configuration

Open **Menu → Default configuration** to edit the profile copied into every new custom scan.

Saving is explicit:

1. Change the desired fields.
2. Select **Save default configuration**.
3. The validated profile is written atomically beside the session database as `web-default-scan.json`.

On Linux and other POSIX systems the file is restricted to mode `0600`.

For safety, default profiles never persist:

- cookies
- proxy values or proxy credentials
- Authorization, Cookie, API-key, token, session, credential or secret-like headers
- the option to reveal sensitive-looking extracted values

These values can still be supplied to a custom scan and remain temporary.

## Custom scan

Open **Menu → Custom scan** to receive a fresh copy of the saved defaults. Modify any field and select **Run custom scan**.

A custom scan:

- uses the edited values for that scan only
- does not update the saved profile
- resets the next custom scan to the saved defaults
- remains subject to the normal request budget, worker limits and validation

Use **Reload saved defaults** to discard the current temporary changes before starting the scan.

## API

The authenticated web API exposes:

```text
GET /api/settings/default-scan
PUT /api/settings/default-scan
```

`PUT` requires the same CSRF protection as scan creation and control actions. Starting a scan remains a separate operation:

```text
POST /api/scans
```

This separation prevents a custom scan from changing the default profile accidentally.
