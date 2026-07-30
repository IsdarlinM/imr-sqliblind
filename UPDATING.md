# Updating imr-sqliblind

Version 0.6.0 adds a native update command for Linux, Termux, and Windows.

## Check for updates

```bash
sqliblind update --check
```

Example output:

```text
Installed version: 0.6.0
Available version: 0.7.0
Repository: https://github.com/IsdarlinM/imr-sqliblind.git
Update available: 0.6.0 -> 0.7.0
```

Structured output:

```bash
sqliblind update --check --json
```

## Install the latest version

```bash
sqliblind update
```

The updater:

1. Reads the available version from the official `main` branch over HTTPS.
2. Uses only the official `IsdarlinM/imr-sqliblind` repository.
3. Refuses an unexpected `origin` repository.
4. Refuses to overwrite a checkout with local changes.
5. Updates `main` using `git pull --ff-only`.
6. Reinstalls the package and web dependencies into the current Python environment.
7. Verifies the installed version after the update.

If the original checkout is unavailable, the command creates a managed official checkout below the application directory and uses it for future updates.

## Options

```text
sqliblind update --check          Check only; do not modify files
sqliblind update                  Install an available update
sqliblind update --force          Reinstall the latest available version
sqliblind update --source PATH    Use an explicit official checkout
sqliblind update --timeout 20     Change the GitHub request timeout
sqliblind update --json           Print structured JSON output
sqliblind update --help           Show updater help
```

## First update from 0.5.1

Version 0.5.1 does not contain the new command. Update once manually:

### Linux and Termux

```bash
cd ~/storage/downloads/imr-sqliblind
git checkout main
git pull --ff-only origin main
chmod +x install.sh
./install.sh
hash -r
sqliblind --version
```

### Windows CMD

```cmd
cd imr-sqliblind
git checkout main
git pull --ff-only origin main
install.cmd
```

After installing 0.6.0, future updates use `sqliblind update`.

## Local changes

The updater intentionally refuses a dirty checkout. Inspect changes with:

```bash
git status
git diff
```

Commit, stash, or discard intentional changes before retrying. The updater never runs `git reset --hard`.
