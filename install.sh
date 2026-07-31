#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="imr-sqliblind"
COMMAND_NAME="sqliblind"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=10
MANAGED_PYTHON="3.12"
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DEFAULT_PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
PREFIX="$DEFAULT_PREFIX"
CUSTOM_PREFIX=0
NO_PATH=0
PYTHON_OVERRIDE=""

usage() {
  cat <<'USAGE'
Usage: ./install.sh [options]

Installs imr-sqliblind for the current user, including the realtime web console.

Options:
  --prefix PATH     Custom installation directory.
  --python PATH     Preferred Python executable (must be Python 3.10+).
  --no-path         Do not persist environment variables or modify PATH.
  -h, --help        Show this help.
USAGE
}

log() { printf '[+] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die() { printf '[x] %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --prefix)
      (($# >= 2)) || die "--prefix requires a path"
      PREFIX="$2"
      CUSTOM_PREFIX=1
      shift 2
      ;;
    --python)
      (($# >= 2)) || die "--python requires an executable path"
      PYTHON_OVERRIDE="$2"
      shift 2
      ;;
    --no-path)
      NO_PATH=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

PREFIX="$(mkdir -p "$PREFIX" && cd "$PREFIX" && pwd -P)"
if ((CUSTOM_PREFIX)); then
  BIN_DIR="$PREFIX/bin"
else
  BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
fi
VENV_DIR="$PREFIX/venv"
BOOTSTRAP_DIR="$PREFIX/bootstrap"
STATE_FILE="$PREFIX/install.env"
COMMAND_PATH="$BIN_DIR/$COMMAND_NAME"
NATIVE_COMMAND_PATH="$VENV_DIR/bin/$COMMAND_NAME"

python_is_compatible() {
  local candidate="$1"
  "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  local candidate resolved
  if [[ -n "$PYTHON_OVERRIDE" ]]; then
    [[ -x "$PYTHON_OVERRIDE" ]] || die "Python executable not found: $PYTHON_OVERRIDE"
    python_is_compatible "$PYTHON_OVERRIDE" || die "--python must point to Python 3.10 or newer"
    printf '%s\n' "$PYTHON_OVERRIDE"
    return 0
  fi

  for candidate in python3 python python3.14 python3.13 python3.12 python3.11 python3.10; do
    resolved="$(command -v "$candidate" 2>/dev/null || true)"
    if [[ -n "$resolved" ]] && python_is_compatible "$resolved"; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

install_uv() {
  local uv="$BOOTSTRAP_DIR/uv"
  if [[ -x "$uv" ]]; then
    printf '%s\n' "$uv"
    return 0
  fi

  mkdir -p "$BOOTSTRAP_DIR"
  log "Installing the uv runtime bootstrapper" >&2
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$BOOTSTRAP_DIR" sh >&2
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="$BOOTSTRAP_DIR" sh >&2
  else
    die "curl or wget is required to install Python automatically"
  fi
  [[ -x "$uv" ]] || die "uv installation did not create $uv"
  printf '%s\n' "$uv"
}

PYTHON_BIN="$(find_python || true)"
UV_BIN=""
if [[ -z "$PYTHON_BIN" ]]; then
  UV_BIN="$(install_uv)"
  log "Installing managed Python $MANAGED_PYTHON"
  "$UV_BIN" python install "$MANAGED_PYTHON"
  PYTHON_BIN="$("$UV_BIN" python find "$MANAGED_PYTHON")"
fi
python_is_compatible "$PYTHON_BIN" || die "Unable to locate Python 3.10 or newer"
log "Using $("$PYTHON_BIN" --version 2>&1) at $PYTHON_BIN"

if [[ -x "$VENV_DIR/bin/python" ]] && ! python_is_compatible "$VENV_DIR/bin/python"; then
  warn "Existing environment uses an unsupported Python; recreating it"
  rm -rf "$VENV_DIR"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  log "Creating isolated environment at $VENV_DIR"
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    UV_BIN="${UV_BIN:-$(install_uv)}"
    rm -rf "$VENV_DIR"
    "$UV_BIN" venv --python "$PYTHON_BIN" "$VENV_DIR"
  fi
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_COMMAND="$NATIVE_COMMAND_PATH"
"$VENV_PYTHON" -m ensurepip --upgrade >/dev/null 2>&1 || true
log "Installing project dependencies and web console"
"$VENV_PYTHON" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
"$VENV_PYTHON" -m pip install --disable-pip-version-check --upgrade "$PROJECT_ROOT[web]"
[[ -x "$VENV_COMMAND" ]] || die "Installation completed without creating $VENV_COMMAND"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/$COMMAND_NAME" <<EOF_WRAPPER
#!/usr/bin/env sh
exec "$VENV_COMMAND" "\$@"
EOF_WRAPPER
chmod 0755 "$BIN_DIR/$COMMAND_NAME"

cat > "$STATE_FILE" <<EOF_STATE
IMR_SQLIBLIND_HOME='$PREFIX'
SQLIBLIND_PYTHON='$VENV_PYTHON'
SQLIBLIND_BIN='$BIN_DIR'
SQLIBLIND_COMMAND='$COMMAND_PATH'
SQLIBLIND_NATIVE_COMMAND='$VENV_COMMAND'
EOF_STATE
chmod 0600 "$STATE_FILE"

remove_profile_block() {
  local profile="$1" temporary
  [[ -f "$profile" ]] || return 0
  temporary="$(mktemp)"
  awk '
    $0 == "# >>> imr-sqliblind >>>" {skip=1; next}
    $0 == "# <<< imr-sqliblind <<<" {skip=0; next}
    !skip {print}
  ' "$profile" > "$temporary"
  mv "$temporary" "$profile"
}

profile_targets() {
  local default_shell="${SHELL##*/}" candidate
  local -a candidates=("$HOME/.profile")

  case "$default_shell" in
    bash) candidates+=("$HOME/.bashrc") ;;
    zsh) candidates+=("$HOME/.zshrc") ;;
  esac

  for candidate in \
    "$HOME/.bash_profile" \
    "$HOME/.bashrc" \
    "$HOME/.zprofile" \
    "$HOME/.zshrc"; do
    [[ -e "$candidate" ]] && candidates+=("$candidate")
  done

  printf '%s\n' "${candidates[@]}" | awk '!seen[$0]++'
}

persist_environment() {
  local profile
  while IFS= read -r profile; do
    touch "$profile"
    remove_profile_block "$profile"
    cat >> "$profile" <<EOF_PROFILE

# >>> imr-sqliblind >>>
export IMR_SQLIBLIND_HOME='$PREFIX'
export SQLIBLIND_PYTHON='$VENV_PYTHON'
export SQLIBLIND_BIN='$BIN_DIR'
export SQLIBLIND_COMMAND='$COMMAND_PATH'
export SQLIBLIND_NATIVE_COMMAND='$VENV_COMMAND'
case ":\$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) export PATH='$BIN_DIR':"\$PATH" ;;
esac
# <<< imr-sqliblind <<<
EOF_PROFILE
  done < <(profile_targets)
}

verify_persisted_environment() {
  local profile found=0
  while IFS= read -r profile; do
    if grep -Fqx "# >>> imr-sqliblind >>>" "$profile" &&
       grep -Fqx "export SQLIBLIND_BIN='$BIN_DIR'" "$profile" &&
       grep -Fq "export PATH='$BIN_DIR':" "$profile"; then
      found=1
      break
    fi
  done < <(profile_targets)

  ((found == 1)) || die "Unable to persist the sqliblind command directory in shell profiles"
}

if ((NO_PATH == 0)); then
  persist_environment
  verify_persisted_environment
fi

export IMR_SQLIBLIND_HOME="$PREFIX"
export SQLIBLIND_PYTHON="$VENV_PYTHON"
export SQLIBLIND_BIN="$BIN_DIR"
export SQLIBLIND_COMMAND="$COMMAND_PATH"
export SQLIBLIND_NATIVE_COMMAND="$VENV_COMMAND"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) export PATH="$BIN_DIR:$PATH" ;;
esac
command -v "$COMMAND_NAME" >/dev/null 2>&1 ||
  die "The sqliblind command is not available after configuring PATH"

log "Verifying CLI, service config, and web console"
"$BIN_DIR/$COMMAND_NAME" --version
"$BIN_DIR/$COMMAND_NAME" config init >/dev/null
"$BIN_DIR/$COMMAND_NAME" web --help >/dev/null
printf '\nInstallation completed.\n'
printf '  Home:    %s\n' "$PREFIX"
printf '  Python:  %s\n' "$VENV_PYTHON"
printf '  Command: %s\n' "$COMMAND_PATH"
printf '  Native:  %s\n' "$VENV_COMMAND"
if ((NO_PATH == 0)); then
  printf '\nPATH was configured automatically for future shells.\n'
  printf 'To refresh this shell now, run: source ~/.profile 2>/dev/null || exec "$SHELL"\n'
fi
