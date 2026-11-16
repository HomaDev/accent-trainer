#!/usr/bin/env bash
set -e

APP_DIR="/dev/accent-trainer"
REPO_URL=$(git config --get remote.origin.url)
CURRENT_USER=$(whoami)

echo "1. Installing system dependencies (ffmpeg, python3-venv, git)..."
sudo apt-get update -y
sudo apt-get install -y ffmpeg python3-venv git

echo "2. Setting up $APP_DIR..."
sudo mkdir -p "$APP_DIR"
sudo chown -R "$CURRENT_USER:$CURRENT_USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" pull
fi

echo "3. Creating virtual environment and installing Python packages..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install fastapi uvicorn python-multipart numpy scipy Pillow

echo "4. Creating permanent systemd service (runs on boot & auto-restarts)..."
sudo tee /etc/systemd/system/accent-trainer.service > /dev/null <<EOF
[Unit]
Description=Japanese Pitch Accent Trainer
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now accent-trainer

echo "5. Enabling automatic GitHub updates every 15 minutes..."
cat <<EOF > "$APP_DIR/auto_update.sh"
#!/usr/bin/env bash
cd "$APP_DIR"
git fetch origin main
if [ "\$(git rev-parse HEAD)" != "\$(git rev-parse origin/main)" ]; then
  git pull origin main
  "$APP_DIR/venv/bin/pip" install -r requirements.txt
  sudo systemctl restart accent-trainer
fi
EOF
chmod +x "$APP_DIR/auto_update.sh"

(crontab -l 2>/dev/null | grep -v "$APP_DIR/auto_update.sh"; echo "*/15 * * * * $APP_DIR/auto_update.sh >/dev/null 2>&1") | crontab -

echo "Done! Accent Trainer is running on http://127.0.0.1:8001"