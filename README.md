# RaPi-Backup: Automated USB Backup Station

A Raspberry Pi 5-based automated backup system that transfers files from USB drives to an external HDD with a touch-friendly GUI, then syncs to Google Drive.

## Features

- **Auto-detect USB drives** - Automatically triggers backup when USB is inserted
- **Touch-friendly GUI** - 7-inch display optimized interface with PEBL branding
- **Progress monitoring** - Real-time transfer progress, speed, ETA, and current file display
- **Duplicate detection** - Checks for existing files before transfer, prompts skip/overwrite
- **Google Drive sync** - Automated cloud backup with configurable schedule (24hr or time window)
- **Cancel button** - Stop transfers mid-process if needed
- **Safe eject** - Proper unmount before USB removal

## Hardware Requirements

- Raspberry Pi 5 (tested with 2GB+ RAM)
- 7-inch touchscreen display (800x480)
- External HDD (NTFS formatted) - tested with WD Elements SE 1.8TB
- USB drives for backup source

## Software Stack

- **OS**: Raspberry Pi OS (64-bit, Bookworm)
- **Desktop**: labwc (Wayland compositor)
- **GUI**: GTK3 with Python (gi.repository)
- **File transfer**: rsync
- **Cloud sync**: rclone with Google Drive
- **USB detection**: udev rules with systemd-run

## Project Structure

```
RaPi/
├── deploy_to_pi.py          # Deploy scripts to Pi via SSH
├── pi_ssh.py                # SSH helper utility
├── scripts/
│   ├── 99-usb-transfer.rules    # udev rules for USB detection
│   ├── on-usb-insert.sh         # Main transfer script
│   ├── transfer-gui.py          # GTK3 GUI application
│   ├── backup-to-gdrive.sh      # Google Drive sync script
│   ├── notify-user.sh           # Desktop notifications
│   ├── status-server.py         # HTTP status endpoint
│   ├── sync-config.json         # Sync schedule config
│   ├── pebl-logo.png            # Logo asset
│   ├── usb-transfer-status.service  # systemd service
│   └── usb-transfer-monitor.desktop # Autostart entry
```

## Installation

### 1. Raspberry Pi Initial Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 \
    rsync ntfs-3g rclone jq

# Create directories
sudo mkdir -p /opt/usb-transfer/assets
sudo mkdir -p /var/log/usb-transfer
sudo mkdir -p /media/usb-source
sudo mkdir -p /media/external-hdd

# Set permissions
sudo chown -R $USER:$USER /opt/usb-transfer
sudo chmod 755 /var/log/usb-transfer
```

### 2. Mount External HDD

Add to `/etc/fstab` for auto-mount:
```
UUID=YOUR-HDD-UUID /media/external-hdd ntfs-3g defaults,nofail,x-systemd.device-timeout=30 0 0
```

Find UUID with:
```bash
sudo blkid /dev/sda1
```

### 3. Configure rclone for Google Drive

```bash
rclone config
# Choose: n (new remote)
# Name: gdrive
# Type: drive (Google Drive)
# Follow OAuth flow in browser
```

### 4. Deploy from Windows

Edit `deploy_to_pi.py` with your Pi's IP and credentials:
```python
PI_HOST = "192.168.1.159"
PI_USER = "pebl"
PI_PASSWORD = "pebl"
```

Run deployment:
```bash
python deploy_to_pi.py
```

### 5. Enable Autostart

```bash
# Copy desktop file for autostart
cp /opt/usb-transfer/usb-transfer-monitor.desktop ~/.config/autostart/

# Or start manually
export DISPLAY=:0
python3 /opt/usb-transfer/transfer-gui.py &
```

## Configuration

### Sync Schedule (`sync-config.json`)

```json
{
    "mode": "24hr",      // or "scheduled"
    "start_hour": 22,    // Start sync at 10 PM
    "end_hour": 6        // End sync at 6 AM
}
```

### Cron Job for Google Drive Sync

```bash
crontab -e
# Add:
*/5 * * * * /opt/usb-transfer/backup-to-gdrive.sh >> /var/log/usb-transfer/cron.log 2>&1
```

## File Locations on Pi

| Path | Purpose |
|------|---------|
| `/opt/usb-transfer/` | Main scripts directory |
| `/opt/usb-transfer/assets/` | Logo and images |
| `/var/log/usb-transfer/transfer.log` | Transfer logs |
| `/var/log/usb-transfer/gdrive-backup.log` | Sync logs |
| `/tmp/usb-transfer-status` | Current status |
| `/tmp/usb-transfer-progress.json` | Progress data |
| `/media/external-hdd/incoming/` | Backup destination |
| `/etc/udev/rules.d/99-usb-transfer.rules` | USB trigger rules |

## How It Works

### USB Detection Flow

1. **USB inserted** → udev rule detects new partition
2. **systemd-run** spawns `on-usb-insert.sh` in proper context
3. **Script waits** for device to settle (8 seconds)
4. **Mount detection** - checks lsblk, /media/pebl/*, findmnt
5. **Manual mount** if not auto-mounted (with 5 retries)
6. **Scan files** and count by extension
7. **Check duplicates** against existing HDD files
8. **User prompt** if duplicates found (skip/overwrite)
9. **rsync transfer** with progress updates
10. **Completion** notification and safe eject

### Progress Updates

The script writes to `/tmp/usb-transfer-progress.json`:
```json
{
    "percent": 45,
    "files_done": 500,
    "files_total": 1143,
    "speed": "35.44MB/s",
    "eta": "0:01:57",
    "status": "transferring",
    "current_file": "photo_001.jpg",
    "message": "Copying: photo_001.jpg (45%)"
}
```

The GUI reads this file every 500ms and updates the display.

### Google Drive Sync

- Creates dated folders: `RaPi-PEBL-Sync/DDMMYY/`
- Uses rclone with bandwidth limit (10MB/s default)
- Excludes: `.Trash-*`, `.lost+found`, `*.tmp`, `*.partial`
- Runs via cron every 5 minutes (or on schedule)

## Troubleshooting

### Check Logs

```bash
# Transfer log
sudo tail -50 /var/log/usb-transfer/transfer.log

# GUI log
cat /tmp/gui.log

# System journal for udev
journalctl -f | grep usb
```

### Common Issues

**USB not detected:**
```bash
# Check udev rules loaded
sudo udevadm control --reload-rules
sudo udevadm trigger

# Check rule syntax
cat /etc/udev/rules.d/99-usb-transfer.rules
```

**Mount permission denied:**
- The script uses `systemd-run` to escape udev's restricted environment
- Check if device is being held by another process: `lsof /dev/sdb1`

**GUI not showing progress:**
- Check JSON file: `cat /tmp/usb-transfer-progress.json`
- The GUI has fallback regex parsing for malformed JSON

**Transfer stuck at 0%:**
- Check rsync is running: `ps aux | grep rsync`
- Check mount: `mount | grep usb`

### Manual Commands

```bash
# Kill stuck transfer
sudo pkill -f on-usb-insert.sh
sudo pkill rsync
sudo rm -f /tmp/usb-transfer.lock

# Manual mount
sudo mount /dev/sdb1 /media/usb-source

# Test rsync
rsync -avh --progress /media/usb-source/ /media/external-hdd/incoming/test/

# Force Google Drive sync
/opt/usb-transfer/backup-to-gdrive.sh --force
```

## Screen Rotation

If your display is upside down, add to `/boot/firmware/config.txt`:
```
display_lcd_rotate=2
```

Or for Wayland/labwc, create `~/.config/kanshi/config`:
```
profile {
    output * transform 180
}
```

## Key Learnings

1. **udev RUN is restricted** - Can't do mounts directly; use `systemd-run --no-block`
2. **Wait for device settle** - USB needs 5-8 seconds before mount
3. **Multiple mount detection methods** - lsblk, findmnt, and /media/user/* checks
4. **JSON parsing robustness** - Shell scripts can produce malformed JSON; GUI needs fallback
5. **Emojis don't render** - Pi display may not have emoji fonts; use text labels
6. **NTFS-3G for Windows drives** - Required for read/write access to NTFS
7. **GTK3 on Wayland** - Works well with labwc compositor
8. **Paramiko for remote deploy** - Easy SSH/SFTP from Windows Python

## Development

### Deploy Changes

From Windows with project open:
```bash
python deploy_to_pi.py
```

### Restart GUI Only

```bash
pkill -f transfer-gui.py
export DISPLAY=:0
python3 /opt/usb-transfer/transfer-gui.py &
```

### Test USB Script Manually

```bash
sudo /opt/usb-transfer/on-usb-insert.sh sdb1 USB_LABEL
```

## License

MIT License - Feel free to use and modify for your own backup projects.

## Credits

Built for PEBL data backup workflow. Developed with Claude Code assistance.
