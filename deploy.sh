#!/bin/bash

# ERPNext Biometric Attendance Service Deployment Script
# Run this script with sudo privileges

set -e

echo "Starting ERPNext Biometric Attendance Service deployment..."

# Configuration
SERVICE_NAME="erpnext-biometric"
SERVICE_USER="ubuntu"
INSTALL_DIR="/opt/erpnext-biometric"
PYTHON_REQUIREMENTS="requests pickledb pyzk"

# Create service user if it doesn't exist
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "Creating service user: $SERVICE_USER"
    useradd -r -s /bin/false -d $INSTALL_DIR $SERVICE_USER
else
    echo "Service user $SERVICE_USER already exists"
fi

# Create installation directory
echo "Creating installation directory: $INSTALL_DIR"
mkdir -p $INSTALL_DIR
mkdir -p $INSTALL_DIR/logs

# Copy application files
echo "Copying application files..."
cp erpnext_sync.py $INSTALL_DIR/
cp erpnext-biometric.service /etc/systemd/system/

# Set proper permissions
echo "Setting permissions..."
chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR
chmod +x $INSTALL_DIR/erpnext_sync.py
chmod 644 /etc/systemd/system/erpnext-biometric.service

# Install Python dependencies
echo "Installing Python dependencies..."
apt update
apt install -y python3 python3-pip

# Install required Python packages
pip3 install $PYTHON_REQUIREMENTS

# Reload systemd and enable service
echo "Configuring systemd service..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME

echo "Deployment completed successfully!"
echo ""
echo "To start the service: sudo systemctl start $SERVICE_NAME"
echo "To check status: sudo systemctl status $SERVICE_NAME"
echo "To view logs: sudo journalctl -u $SERVICE_NAME -f"
echo "To stop the service: sudo systemctl stop $SERVICE_NAME"
echo ""
echo "Service will automatically start on boot."