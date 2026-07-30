# Updating imr-sqliblind

`imr-sqliblind` does not currently provide a `sqliblind update` subcommand.
Update the source checkout from GitHub and rerun the native installer. The installer refreshes the isolated environment and the global `sqliblind` wrapper.

## Linux and Termux

Run these commands from the cloned repository:

```bash
git checkout main
git pull --ff-only origin main
chmod +x install.sh
./install.sh
hash -r
sqliblind --version
```

Example when the repository is under Android shared storage:

```bash
cd ~/storage/downloads/imr-sqliblind
git checkout main
git pull --ff-only origin main
chmod +x install.sh
./install.sh
hash -r
sqliblind --version
```

The expected current version is:

```text
sqliblind 0.5.1
```

If the shell still reports an older version, reload the profile and clear the command cache:

```bash
source ~/.profile 2>/dev/null || true
hash -r
command -v sqliblind
sqliblind --version
```

## Windows CMD

Run from the cloned repository:

```cmd
git checkout main
git pull --ff-only origin main
install.cmd
```

Open a new CMD window and verify:

```cmd
where sqliblind
sqliblind --version
```

## Fresh checkout

If the original repository directory was deleted or is not a Git checkout, clone it again and run the installer:

```bash
git clone https://github.com/IsdarlinM/imr-sqliblind.git
cd imr-sqliblind
./install.sh
```

Windows:

```cmd
git clone https://github.com/IsdarlinM/imr-sqliblind.git
cd imr-sqliblind
install.cmd
```

## Local changes

`git pull --ff-only` intentionally refuses updates that require a merge. Before updating, inspect any local modifications:

```bash
git status
git diff
```

Commit, stash, or discard intentional local changes before repeating the update. Do not use `git reset --hard` unless you explicitly intend to delete those changes.
