#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="imr-sqliblind"
DEFAULT_PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_NAME"
PREFIX="$DEFAULT_PREFIX"
CUSTOM_PREFIX=0
NO_PATH=0

usage() {
  cat <<'USAGE'
Usage: ./uninstall.sh [--prefix PATH] [--no-path]
USAGE
}

die() { printf '[x] %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --prefix)
      (($# >= 2)) || die "--prefix requires a path"
      PREFIX="$2"
      CUSTOM_PREFIX=1
      shift 2
      ;;
    --no-path) NO_PATH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

if ((CUSTOM_PREFIX)); then
  BIN_DIR="$PREFIX/bin"
else
  BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
fi

if [[ -f "$PREFIX/install.env" ]]; then
  # shellcheck disable=SC1090
  source "$PREFIX/install.env"
  BIN_DIR="${SQLIBLIND_BIN:-$BIN_DIR}"
fi

case "$PREFIX" in
  ""|/|"$HOME") die "Refusing to remove unsafe prefix: $PREFIX" ;;
esac

rm -f "$BIN_DIR/sqliblind"
rm -rf "$PREFIX"

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

if ((NO_PATH == 0)); then
  for profile in \
    "$HOME/.profile" \
    "$HOME/.bash_profile" \
    "$HOME/.bashrc" \
    "$HOME/.zprofile" \
    "$HOME/.zshrc"; do
    remove_profile_block "$profile"
  done
fi

printf 'imr-sqliblind was removed. Open a new shell to refresh PATH.\n'
