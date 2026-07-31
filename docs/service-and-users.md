# Authenticated background service and user management

`imr-sqliblind` 0.8.0 can run its realtime web console as a detached user-level service. The service is managed by the installed `sqliblind` command and does not require administrator/root privileges.

## Quick start

```bash
sqliblind start
sqliblind status
sqliblind stop
sqliblind restart
```

The default endpoint is:

```text
http://127.0.0.1:43127/
```

The deliberately unusual default port is `43127`. Override it for one start without changing the saved configuration:

```bash
sqliblind start --port 43128
sqliblind restart --host 127.0.0.1 --port 43129
```

Use `--foreground` for diagnostics:

```bash
sqliblind start --foreground
```

## Bootstrap administrator

When the user database is empty, the first service start creates:

```text
Username: admin
Password: admin
```

This bootstrap account is marked `must_change_password`. The browser redirects it to the password-change screen and denies access to the console/API until the password has been replaced. Changing or resetting a password revokes all existing sessions for that user.

The default service binds only to `127.0.0.1`. Do not expose `admin:admin` to another device. Configure the final administrator password before enabling remote access.

## Browser administration

After replacing the bootstrap password, administrators can open:

```text
http://127.0.0.1:43127/admin/
```

The browser page supports:

- creating permanent or temporary users;
- assigning `admin`, `operator`, or `viewer` roles;
- enabling and disabling accounts;
- changing or removing expiration;
- resetting passwords and requiring another change at next login;
- deleting users while preserving the last usable administrator.

All browser actions require the authenticated administrator session and its CSRF token. The page calls the same validated user store used by the CLI and HTTP administration API.

## User commands

Create permanent users:

```bash
sqliblind users create analyst --role operator
sqliblind users create auditor --role viewer
sqliblind users create backup-admin --role admin
```

Create temporary users:

```bash
sqliblind users create contractor --role operator --expires-in 12h
sqliblind users create reviewer --role viewer --expires-in 7d
```

Supported durations are minutes, hours, days, and weeks: `30m`, `12h`, `7d`, `2w`.

List and change users:

```bash
sqliblind users list
sqliblind users passwd analyst
sqliblind users role analyst viewer
sqliblind users disable analyst
sqliblind users enable analyst
sqliblind users expire analyst --in 24h
sqliblind users expire analyst --never
sqliblind users delete analyst
sqliblind users audit --limit 100
```

Passwords are prompted without echo. For controlled automation, provide exactly one password line through standard input:

```bash
printf '%s\n' 'Strong-Temporary-Password9' | \
  sqliblind users create ci-operator --role operator --expires-in 2h --password-stdin
```

There is intentionally no `--password` argument, which avoids leaking credentials through shell history and process listings.

## Roles

- `admin`: manage users, inspect audit events, change defaults, and operate scans.
- `operator`: create, pause, resume, and stop scans; read sessions and exports.
- `viewer`: read the console, sessions, events, graph, tables, and exports; write operations are denied.

The store prevents deletion, disabling, demotion, or temporary expiration of the last usable administrator.

## Configuration

Create or locate the default configuration:

```bash
sqliblind config init
sqliblind config show
```

Default paths:

```text
Windows:
  %LOCALAPPDATA%\Programs\imr-sqliblind\config\service.json

POSIX:
  ~/.local/share/imr-sqliblind/config/service.json
```

A generated configuration contains:

```json
{
  "allow_remote": false,
  "auth_database": "<application-root>/auth/users.db",
  "host": "127.0.0.1",
  "log_file": "<application-root>/logs/service.log",
  "port": 43127,
  "session_hours": 12,
  "ssl_certfile": null,
  "ssl_keyfile": null,
  "state_file": "<application-root>/run/service.json",
  "workspace": "<application-root>/workspaces"
}
```

Update persistent defaults:

```bash
sqliblind config set --port 43128
sqliblind config set --session-hours 8
sqliblind config set --workspace /srv/sqliblind/workspaces
sqliblind config set --log-file /var/log/sqliblind/service.log
```

Use another configuration file:

```bash
sqliblind start --config ./service.json
sqliblind users --config ./service.json list
sqliblind config --config ./service.json show
```

Writes use an atomic replace. On POSIX, configuration, service state, and the user database are created with user-only permissions where the filesystem permits it.

## Remote service access

Remote binding requires an explicit persistent opt-in:

```bash
sqliblind config set --host 0.0.0.0 --allow-remote
```

Remote HTTP sends credentials, cookies, scan metadata, and results without transport encryption. Prefer TLS:

```bash
sqliblind config set \
  --host 0.0.0.0 \
  --allow-remote \
  --ssl-certfile /path/server.crt \
  --ssl-keyfile /path/server.key
```

The certificate and key must both exist. Authentication cookies are marked `Secure` when TLS is enabled.

## Storage and session security

- Passwords use PBKDF2-HMAC-SHA-256 with a unique random 128-bit salt and 310,000 iterations.
- Password comparison uses constant-time digest comparison.
- User sessions use random 256-bit tokens; only SHA-256 token hashes are stored.
- Sessions are checked against user activation, user expiration, session expiration, and an authentication version on every request.
- Password, role, activation, and expiration changes revoke sessions.
- Browser mutations require CSRF tokens.
- Login responses do not reveal whether a username exists and repeated failures are rate-limited.
- Service stop uses a random control token kept in the user-only state file. It requests a graceful Uvicorn shutdown instead of terminating an unverified PID.
- Authentication and account-management actions are retained in the SQLite audit table without recording passwords or session tokens.

## Service files

`sqliblind status` prints the effective URL, PID, configuration path, log file, and authentication database. The service state file is removed after a clean shutdown. Stale state is removed when its PID no longer exists.

Updates and reinstalls preserve the application data root, including service configuration, workspaces, users, audit events, and logs.
