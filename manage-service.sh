#!/bin/bash

# ERPNext Biometric Service Management Script

SERVICE_NAME="erpnext-biometric"

case "$1" in
    start)
        echo "Starting $SERVICE_NAME service..."
        sudo systemctl start $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    stop)
        echo "Stopping $SERVICE_NAME service..."
        sudo systemctl stop $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    restart)
        echo "Restarting $SERVICE_NAME service..."
        sudo systemctl restart $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    status)
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    logs)
        echo "Showing logs for $SERVICE_NAME (Press Ctrl+C to exit)..."
        sudo journalctl -u $SERVICE_NAME -f
        ;;
    enable)
        echo "Enabling $SERVICE_NAME to start on boot..."
        sudo systemctl enable $SERVICE_NAME
        ;;
    disable)
        echo "Disabling $SERVICE_NAME from starting on boot..."
        sudo systemctl disable $SERVICE_NAME
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|enable|disable}"
        echo ""
        echo "Commands:"
        echo "  start    - Start the service"
        echo "  stop     - Stop the service"
        echo "  restart  - Restart the service"
        echo "  status   - Show service status"
        echo "  logs     - Show live logs"
        echo "  enable   - Enable service to start on boot"
        echo "  disable  - Disable service from starting on boot"
        exit 1
        ;;
esac