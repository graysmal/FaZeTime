#!/usr/bin/env bash
# Install/update the remote ASR service on the VM. Run as root ON THE VM from a copy of services/asr_remote:
#   bash deploy/install.sh [MODEL...]
# Needs /usr/local/bin/uv. Does not touch the token: /etc/fazetime-asr.env is installed separately (0600).
# Creates no cloud resources; only local files, a system user and one systemd unit.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/fazetime-asr/app
MODELS=/opt/fazetime-asr/models
export UV_PYTHON_INSTALL_DIR=/opt/fazetime-asr/python UV_PYTHON_PREFERENCE=only-managed HF_HUB_DISABLE_TELEMETRY=1
id fazetime-asr >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin fazetime-asr
install -d -m 755 "$APP" "$APP/fazetime_asr_remote" "$MODELS"
install -m 644 "$SRC/pyproject.toml" "$SRC/uv.lock" "$APP/"
install -m 644 "$SRC"/fazetime_asr_remote/*.py "$APP/fazetime_asr_remote/"
cd "$APP"
uv python install 3.12
uv sync --frozen --no-dev
for m in "${@:-distil-small.en}"; do
  .venv/bin/python -I -c "import sys; from faster_whisper import download_model; print(download_model(sys.argv[1], cache_dir=sys.argv[2]))" "$m" "$MODELS"
done
chmod -R a+rX /opt/fazetime-asr
test -f /etc/fazetime-asr.env || { echo "missing /etc/fazetime-asr.env (ASR_REMOTE_TOKEN)"; exit 1; }
chown root:root /etc/fazetime-asr.env && chmod 600 /etc/fazetime-asr.env
install -m 644 "$SRC/deploy/fazetime-asr.service" /etc/systemd/system/fazetime-asr.service
systemctl daemon-reload
systemctl enable fazetime-asr.service
systemctl restart fazetime-asr.service
