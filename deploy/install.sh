#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/megatronics
SERVICE_USER=megatronics

install_static_ffmpeg() {
  local arch static_arch archive_dir url tmp
  arch=$(uname -m)
  case "$arch" in
    aarch64|arm64) static_arch=arm64 ;;
    x86_64) static_arch=amd64 ;;
    *) echo "Static ffmpeg fallback does not support architecture: $arch" >&2; return 1 ;;
  esac
  url="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${static_arch}-static.tar.xz"
  tmp=$(mktemp -d)
  if ! curl -fL "$url" -o "$tmp/ffmpeg.tar.xz"; then
    rm -rf "$tmp"
    return 1
  fi
  if ! tar -xJf "$tmp/ffmpeg.tar.xz" -C "$tmp"; then
    rm -rf "$tmp"
    return 1
  fi
  archive_dir=$(find "$tmp" -maxdepth 1 -type d -name 'ffmpeg-*-static' -print -quit)
  if [[ -z "$archive_dir" || ! -x "$archive_dir/ffmpeg" ]] || ! install -m 0755 "$archive_dir/ffmpeg" /usr/local/bin/ffmpeg; then
    rm -rf "$tmp"
    return 1
  fi
  if [[ -x "$archive_dir/ffprobe" ]]; then install -m 0755 "$archive_dir/ffprobe" /usr/local/bin/ffprobe; fi
  rm -rf "$tmp"
}

if [[ $EUID -ne 0 ]]; then echo "Run with sudo: sudo bash deploy/install.sh" >&2; exit 1; fi
if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y software-properties-common curl ca-certificates graphviz python3.12 python3.12-venv python3.12-dev build-essential
  apt-get install -y fonts-noto-naskh-arabic || apt-get install -y fonts-noto-core || echo "Noto Naskh Arabic font package unavailable; continuing."
  apt-get install -y fonts-noto-color-emoji || apt-get install -y fonts-noto-emoji || echo "Noto emoji font package unavailable; emojis may not render."
  if ! apt-get install -y ffmpeg && ! apt-get install -y ffmpeg-free; then
    install_static_ffmpeg || echo "Static ffmpeg download/install failed; voice transcription may be limited." >&2
  fi
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y curl ca-certificates graphviz python3.12 python3.12-devel gcc
  dnf install -y google-noto-naskh-arabic-fonts || dnf install -y google-noto-arabic-fonts || echo "Noto Naskh Arabic font package unavailable; continuing."
  dnf install -y google-noto-color-emoji-fonts || dnf install -y google-noto-emoji-fonts || echo "Noto emoji font package unavailable; emojis may not render."
  if ! dnf install -y ffmpeg && ! dnf install -y ffmpeg-free; then
    install_static_ffmpeg || echo "Static ffmpeg download/install failed; voice transcription may be limited." >&2
  fi
else
  echo "Unsupported OS; install Python 3.12, Graphviz and Noto Naskh Arabic manually." >&2; exit 1
fi
if command -v fc-list >/dev/null 2>&1 && ! fc-list | grep -qi "Noto Naskh Arabic"; then
  echo "Noto Naskh Arabic font not found; downloading from the official Noto repository."
  mkdir -p /usr/share/fonts/truetype/noto
  curl -sSLo /usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoNaskhArabic/NotoNaskhArabic-Regular.ttf || true
  curl -sSLo /usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoNaskhArabic/NotoNaskhArabic-Bold.ttf || true
fi
if command -v fc-cache >/dev/null 2>&1; then fc-cache -f >/dev/null 2>&1 || true; fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$SERVICE_USER"; fi
mkdir -p "$APP_DIR" "$APP_DIR/data"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then python3.12 -m venv "$APP_DIR/.venv"; fi
if [[ ! -f "$APP_DIR/requirements.txt" ]]; then echo "Copy the project into $APP_DIR before running this installer." >&2; exit 1; fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
if ! command -v typst >/dev/null 2>&1; then
  ARCH=$(uname -m)
  case "$ARCH" in x86_64) TARCH=x86_64-unknown-linux-musl;; aarch64|arm64) TARCH=aarch64-unknown-linux-musl;; *) echo "Unsupported Typst architecture: $ARCH" >&2; exit 1;; esac
  VERSION=$(curl -fsSL https://api.github.com/repos/typst/typst/releases/latest | python3.12 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')
  TMP=$(mktemp -d)
  curl -fsSL "https://github.com/typst/typst/releases/download/${VERSION}/typst-${TARCH}.tar.xz" -o "$TMP/typst.tar.xz"
  tar -xf "$TMP/typst.tar.xz" -C "$TMP"
  install -m 0755 "$TMP/typst-${TARCH}/typst" /usr/local/bin/typst
  rm -rf "$TMP"
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
install -m 0644 "$APP_DIR/deploy/megatronics-bot.service" /etc/systemd/system/megatronics-bot.service
systemctl daemon-reload
mkdir -p /var/backups/megatronics
printf '# Daily Megatronics bot backup (keeps the last 7)\n0 3 * * * root APP_DIR=%s BACKUP_DIR=/var/backups/megatronics KEEP=7 bash %s/deploy/backup.sh >/dev/null 2>&1\n' "$APP_DIR" "$APP_DIR" > /etc/cron.d/megatronics-backup
chmod 0644 /etc/cron.d/megatronics-backup
echo "Installed. Add $APP_DIR/.env, then run: systemctl enable --now megatronics-bot"
