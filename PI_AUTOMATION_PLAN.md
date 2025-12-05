# Raspberry Pi USB Automation System - Implementation Plan

## Overview
Automated system that:
1. Detects USB drive insertion → transfers data to external HDD
2. Notifies user when complete → prompts safe ejection
3. Nightly scheduled backup → syncs external HDD to Google Drive

---

## System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   USB Drive     │───▶│  Raspberry Pi    │───▶│  External HDD   │
│   (Source)      │    │  (Controller)    │    │  (Local Backup) │
└─────────────────┘    └────────┬─────────┘    └─────────────────┘
                                │
                                │ Nightly Sync
                                ▼
                       ┌─────────────────┐
                       │  Google Drive   │
                       │  (Cloud Backup) │
                       └─────────────────┘
```

---

## Phase 1: Initial Pi Setup

### 1.1 Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### 1.2 Install Required Packages
```bash
sudo apt install -y \
    udisks2 \
    ntfs-3g \
    exfat-fuse \
    exfat-utils \
    rsync \
    rclone \
    libnotify-bin \
    pmount \
    jq
```

### 1.3 Create Directory Structure
```bash
sudo mkdir -p /media/usb-source
sudo mkdir -p /media/external-hdd
sudo mkdir -p /opt/usb-transfer
sudo mkdir -p /var/log/usb-transfer
```

---

## Phase 2: External HDD Persistent Mount

### 2.1 Identify External HDD
```bash
lsblk -f
# Note the UUID of your external HDD
```

### 2.2 Add to /etc/fstab for Auto-Mount
```bash
# Get UUID
sudo blkid /dev/sdX1

# Add to fstab (example)
UUID=YOUR-HDD-UUID /media/external-hdd ext4 defaults,nofail 0 2
```

### 2.3 Test Mount
```bash
sudo mount -a
```

---

## Phase 3: USB Hotplug Detection (udev Rules)

### 3.1 Create udev Rule
**File:** `/etc/udev/rules.d/99-usb-transfer.rules`
```bash
# Trigger on USB storage device insertion
ACTION=="add", SUBSYSTEM=="block", ENV{ID_USB_DRIVER}=="usb-storage", \
    ENV{DEVTYPE}=="partition", \
    RUN+="/opt/usb-transfer/on-usb-insert.sh %k %E{ID_FS_LABEL}"
```

### 3.2 Reload udev Rules
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

## Phase 4: Transfer Script

### 4.1 Main Transfer Script
**File:** `/opt/usb-transfer/on-usb-insert.sh`

```bash
#!/bin/bash
# USB Auto-Transfer Script
# Triggered by udev when USB drive is inserted

DEVICE="/dev/$1"
LABEL="${2:-USB_DRIVE}"
MOUNT_POINT="/media/usb-source"
DEST_DIR="/media/external-hdd/incoming"
LOG_FILE="/var/log/usb-transfer/transfer.log"
STATUS_FILE="/tmp/usb-transfer-status"
LOCK_FILE="/tmp/usb-transfer.lock"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Prevent multiple instances
if [ -f "$LOCK_FILE" ]; then
    log "Transfer already in progress. Exiting."
    exit 1
fi
touch "$LOCK_FILE"

# Cleanup function
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# Start transfer
log "=========================================="
log "USB Drive detected: $DEVICE (Label: $LABEL)"

# Wait for device to settle
sleep 3

# Mount USB drive
log "Mounting $DEVICE to $MOUNT_POINT"
sudo mount "$DEVICE" "$MOUNT_POINT" -o ro

if [ $? -ne 0 ]; then
    log "ERROR: Failed to mount $DEVICE"
    exit 1
fi

# Create destination folder with timestamp
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
DEST_FOLDER="$DEST_DIR/${LABEL}_${TIMESTAMP}"
mkdir -p "$DEST_FOLDER"

# Calculate total size
TOTAL_SIZE=$(du -sh "$MOUNT_POINT" | cut -f1)
log "Starting transfer of $TOTAL_SIZE to $DEST_FOLDER"

# Transfer with progress
echo "TRANSFERRING" > "$STATUS_FILE"
rsync -avh --progress "$MOUNT_POINT/" "$DEST_FOLDER/" 2>&1 | tee -a "$LOG_FILE"

if [ ${PIPESTATUS[0]} -eq 0 ]; then
    log "Transfer completed successfully!"
    echo "COMPLETE" > "$STATUS_FILE"

    # Sync filesystem
    sync

    # Unmount USB
    sudo umount "$MOUNT_POINT"
    log "USB unmounted. Safe to remove."

    # Notify user (multiple methods)
    /opt/usb-transfer/notify-user.sh "Transfer Complete" "Safe to remove USB drive ($LABEL). Transferred: $TOTAL_SIZE"
else
    log "ERROR: Transfer failed!"
    echo "FAILED" > "$STATUS_FILE"
    /opt/usb-transfer/notify-user.sh "Transfer Failed" "Error transferring from $LABEL. Check logs."
fi

log "=========================================="
```

### 4.2 Make Executable
```bash
sudo chmod +x /opt/usb-transfer/on-usb-insert.sh
```

---

## Phase 5: User Notification System

### 5.1 Notification Script
**File:** `/opt/usb-transfer/notify-user.sh`

```bash
#!/bin/bash
# Multi-method notification script

TITLE="$1"
MESSAGE="$2"

# Method 1: Desktop notification (if display available)
if [ -n "$DISPLAY" ]; then
    notify-send "$TITLE" "$MESSAGE"
fi

# Method 2: Console broadcast
wall "$TITLE: $MESSAGE"

# Method 3: LED/Buzzer (GPIO) - Optional
# Blink LED on GPIO pin 17 for visual indication
if command -v gpio &> /dev/null; then
    gpio -g mode 17 out
    for i in {1..5}; do
        gpio -g write 17 1
        sleep 0.3
        gpio -g write 17 0
        sleep 0.3
    done
fi

# Method 4: Audio notification
if command -v espeak &> /dev/null; then
    espeak "$MESSAGE" 2>/dev/null
fi

# Method 5: Write to status display (if LCD connected)
echo "$MESSAGE" > /tmp/lcd-message 2>/dev/null

# Method 6: Log for web dashboard
echo "{\"time\": \"$(date -Iseconds)\", \"title\": \"$TITLE\", \"message\": \"$MESSAGE\"}" >> /var/log/usb-transfer/notifications.json
```

### 5.2 Optional: Simple Web Status Page
**File:** `/opt/usb-transfer/status-server.py`

```python
#!/usr/bin/env python3
"""Simple web server to show transfer status"""

from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os

class StatusHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            status = "IDLE"
            if os.path.exists('/tmp/usb-transfer-status'):
                with open('/tmp/usb-transfer-status') as f:
                    status = f.read().strip()

            self.wfile.write(json.dumps({"status": status}).encode())
        else:
            super().do_GET()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), StatusHandler)
    print("Status server running on port 8080")
    server.serve_forever()
```

---

## Phase 6: Google Drive Backup (rclone)

### 6.1 Configure rclone for Google Drive
```bash
rclone config
# Follow prompts:
# n) New remote
# name> gdrive
# Storage> Google Drive
# Follow OAuth flow (will need browser access)
```

### 6.2 Test Connection
```bash
rclone lsd gdrive:
```

### 6.3 Create Backup Script
**File:** `/opt/usb-transfer/backup-to-gdrive.sh`

```bash
#!/bin/bash
# Nightly backup to Google Drive

SOURCE_DIR="/media/external-hdd"
GDRIVE_DEST="gdrive:PiBackups"
LOG_FILE="/var/log/usb-transfer/gdrive-backup.log"
BANDWIDTH_LIMIT="10M"  # Limit to 10MB/s to not saturate connection

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Starting nightly Google Drive backup"

# Check if external HDD is mounted
if ! mountpoint -q "$SOURCE_DIR"; then
    log "ERROR: External HDD not mounted at $SOURCE_DIR"
    exit 1
fi

# Calculate what needs to sync
CHANGES=$(rclone check "$SOURCE_DIR" "$GDRIVE_DEST" --one-way 2>&1 | grep -c "not in")
log "Files to sync: approximately $CHANGES"

# Perform sync with bandwidth limit
rclone sync "$SOURCE_DIR" "$GDRIVE_DEST" \
    --bwlimit "$BANDWIDTH_LIMIT" \
    --progress \
    --log-file="$LOG_FILE" \
    --log-level INFO \
    --transfers 4 \
    --checkers 8 \
    --exclude ".Trash-*/**" \
    --exclude ".lost+found/**"

if [ $? -eq 0 ]; then
    log "Backup completed successfully!"

    # Get storage usage
    USAGE=$(rclone about gdrive: --json | jq -r '.used // "unknown"')
    log "Google Drive usage: $USAGE"
else
    log "ERROR: Backup failed!"
fi

log "=========================================="
```

### 6.4 Make Executable
```bash
sudo chmod +x /opt/usb-transfer/backup-to-gdrive.sh
```

---

## Phase 7: Scheduled Backup (Cron)

### 7.1 Add Cron Job for Nightly Backup
```bash
sudo crontab -e
```

Add the following line (runs at 2 AM):
```cron
0 2 * * * /opt/usb-transfer/backup-to-gdrive.sh >> /var/log/usb-transfer/cron.log 2>&1
```

### 7.2 Optional: Verify Network is Quiet Before Backup
**File:** `/opt/usb-transfer/smart-backup.sh`

```bash
#!/bin/bash
# Only backup if network usage is low

# Check current network usage (packets per second)
PACKETS_BEFORE=$(cat /sys/class/net/eth0/statistics/rx_packets)
sleep 5
PACKETS_AFTER=$(cat /sys/class/net/eth0/statistics/rx_packets)
PACKETS_PER_SEC=$(( (PACKETS_AFTER - PACKETS_BEFORE) / 5 ))

if [ $PACKETS_PER_SEC -lt 100 ]; then
    echo "Network is quiet ($PACKETS_PER_SEC pps). Starting backup..."
    /opt/usb-transfer/backup-to-gdrive.sh
else
    echo "Network busy ($PACKETS_PER_SEC pps). Delaying backup by 30 minutes..."
    sleep 1800
    /opt/usb-transfer/backup-to-gdrive.sh
fi
```

---

## Phase 8: Service Management (systemd)

### 8.1 Create systemd Service for Status Server
**File:** `/etc/systemd/system/usb-transfer-status.service`

```ini
[Unit]
Description=USB Transfer Status Web Server
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/usb-transfer
ExecStart=/usr/bin/python3 /opt/usb-transfer/status-server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 8.2 Enable Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable usb-transfer-status
sudo systemctl start usb-transfer-status
```

---

## Phase 9: Testing & Validation

### 9.1 Test Checklist
- [ ] External HDD mounts on boot
- [ ] USB insertion triggers udev rule
- [ ] Transfer script runs and copies files
- [ ] Notification is received
- [ ] USB can be safely removed
- [ ] rclone connects to Google Drive
- [ ] Nightly backup runs successfully
- [ ] Status web page is accessible

### 9.2 Test Commands
```bash
# Test udev rule manually
sudo udevadm test /sys/block/sdb/sdb1

# Test transfer script manually
sudo /opt/usb-transfer/on-usb-insert.sh sdb1 TEST_USB

# Test rclone sync (dry run)
rclone sync /media/external-hdd gdrive:PiBackups --dry-run

# Check cron logs
tail -f /var/log/usb-transfer/cron.log
```

---

## File Summary

| File | Purpose |
|------|---------|
| `/etc/udev/rules.d/99-usb-transfer.rules` | Triggers on USB insertion |
| `/opt/usb-transfer/on-usb-insert.sh` | Main transfer logic |
| `/opt/usb-transfer/notify-user.sh` | User notification |
| `/opt/usb-transfer/backup-to-gdrive.sh` | Google Drive sync |
| `/opt/usb-transfer/status-server.py` | Web status dashboard |
| `/var/log/usb-transfer/` | All logs |

---

## Security Considerations

1. **Read-only USB mount** - Prevents accidental modification of source
2. **Lock file** - Prevents concurrent transfers
3. **rclone encryption** - Consider encrypting sensitive data before upload
4. **Firewall** - Limit status server to local network only
5. **Permissions** - Scripts run as root (via udev), consider dedicated user

---

## Optional Enhancements

1. **Email notifications** - Send email on transfer complete/failure
2. **Telegram bot** - Push notifications to phone
3. **LCD display** - Show real-time transfer progress
4. **LED indicators** - Visual status (transferring/complete/error)
5. **File verification** - MD5/SHA checksums after transfer
6. **Duplicate detection** - Skip files already transferred
7. **Compression** - Compress before cloud upload to save space
8. **Incremental backups** - Only upload changed files (rclone does this)

---

## Next Steps

1. SSH into Pi and run Phase 1 setup commands
2. Connect and mount external HDD (Phase 2)
3. Create and test udev rules (Phase 3)
4. Deploy and test transfer script (Phase 4)
5. Set up notifications (Phase 5)
6. Configure rclone for Google Drive (Phase 6)
7. Set up cron for nightly backups (Phase 7)
8. Test entire workflow end-to-end (Phase 9)
