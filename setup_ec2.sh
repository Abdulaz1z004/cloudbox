#!/bin/bash
# CloudBox EC2 Setup Script
# Run once after launching a fresh Ubuntu 22.04 instance

set -e

echo "=== Updating system packages ==="
sudo apt-get update -y
sudo apt-get upgrade -y

echo "=== Installing Python, pip, nginx ==="
sudo apt-get install -y python3 python3-pip python3-venv nginx git

echo "=== Creating app directory ==="
sudo mkdir -p /opt/cloudbox
sudo chown ubuntu:ubuntu /opt/cloudbox

echo "=== Copying application files ==="
cp -r ~/cloudbox/* /opt/cloudbox/

echo "=== Creating Python virtual environment ==="
cd /opt/cloudbox
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Creating environment file ==="
# Edit the values below before running!
cat > /opt/cloudbox/.env << 'EOF'
DATABASE_HOST=YOUR_RDS_ENDPOINT_HERE
DATABASE_PORT=5432
DATABASE_NAME=cloudbox
DATABASE_USER=cloudbox_admin
DATABASE_PASSWORD=YOUR_DB_PASSWORD_HERE
STORAGE_BUCKET=YOUR_S3_BUCKET_NAME_HERE
CLOUD_REGION=us-east-1
APP_SECRET=change-this-to-a-long-random-string-in-production
EOF

echo "=== Creating systemd service ==="
sudo tee /etc/systemd/system/cloudbox.service > /dev/null << 'EOF'
[Unit]
Description=CloudBox Flask Application
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/cloudbox
EnvironmentFile=/opt/cloudbox/.env
ExecStart=/opt/cloudbox/venv/bin/gunicorn --workers 4 --bind 127.0.0.1:5000 --timeout 300 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "=== Configuring nginx ==="
sudo tee /etc/nginx/sites-available/cloudbox > /dev/null << 'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 500M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/cloudbox /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

echo "=== Starting services ==="
sudo systemctl daemon-reload
sudo systemctl enable cloudbox
sudo systemctl start cloudbox
sudo systemctl restart nginx

echo ""
echo "=========================================="
echo "CloudBox setup complete!"
echo ""
echo "IMPORTANT: Edit /opt/cloudbox/.env with"
echo "your real RDS endpoint, passwords, and"
echo "S3 bucket name before using the app."
echo ""
echo "Check logs: sudo journalctl -u cloudbox -f"
echo "=========================================="
