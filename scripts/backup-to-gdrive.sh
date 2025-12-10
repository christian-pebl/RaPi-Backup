#!/bin/bash
# Google Drive Backup with Progress Reporting
# Supports 24hr mode (always sync) or scheduled window

SOURCE_DIR="/media/external-hdd/incoming"
LOG_FILE="/var/log/usb-transfer/gdrive-backup.log"
SYNC_STATUS_FILE="/tmp/gdrive-sync-status.json"
SYNC_CONFIG_FILE="/opt/usb-transfer/sync-config.json"
LOCK_FILE="/tmp/gdrive-sync.lock"
USB_TRANSFER_LOCK="/tmp/usb-transfer.lock"
USB_TRANSFER_STATUS="/tmp/usb-transfer-status"
BANDWIDTH_LIMIT="10M"
RCLONE_CONFIG="/home/pebl/.config/rclone/rclone.conf"

# Check for existing sync process (prevent duplicates)
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null)
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - [DEBUG] Sync already running (PID $LOCK_PID), exiting" >> "$LOG_FILE"
        exit 0
    fi
    # Stale lock file, remove it
    rm -f "$LOCK_FILE"
fi

# Check if USB transfer is in progress - wait for it to complete first
if [ -f "$USB_TRANSFER_LOCK" ]; then
    USB_STATUS=""
    [ -f "$USB_TRANSFER_STATUS" ] && USB_STATUS=$(cat "$USB_TRANSFER_STATUS" 2>/dev/null)
    echo "$(date '+%Y-%m-%d %H:%M:%S') - [DEBUG] USB transfer in progress (status: $USB_STATUS), skipping sync to prioritize transfer" >> "$LOG_FILE"
    exit 0
fi

# Create lock file with our PID
echo $$ > "$LOCK_FILE"

# Cleanup lock on exit
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# Device name for folder naming
DEVICE_NAME="RaPi-PEBL"

# Get today's date for folder naming
TODAY=$(date '+%d%m%y')
GDRIVE_DEST="gdrive:${DEVICE_NAME}-Sync/${TODAY}"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

update_sync_status() {
    local active="$1"
    local pct="${2:-0}"
    local synced="${3:-0}"
    local remaining="${4:-0}"
    local speed="${5:---}"

    cat > "$SYNC_STATUS_FILE" << EOF
{
    "active": $active,
    "percent": $pct,
    "files_synced": $synced,
    "files_remaining": $remaining,
    "speed": "$speed",
    "folder": "${DEVICE_NAME}-Sync/${TODAY}",
    "last_sync": "$(date '+%Y-%m-%d %H:%M')",
    "timestamp": "$(date -Iseconds)"
}
EOF
}

# Load sync config
SYNC_MODE="scheduled"
SYNC_START=22
SYNC_END=6

if [ -f "$SYNC_CONFIG_FILE" ]; then
    SYNC_MODE=$(jq -r '.mode // "scheduled"' "$SYNC_CONFIG_FILE" 2>/dev/null)
    SYNC_START=$(jq -r '.start_hour // 22' "$SYNC_CONFIG_FILE" 2>/dev/null)
    SYNC_END=$(jq -r '.end_hour // 6' "$SYNC_CONFIG_FILE" 2>/dev/null)
fi

log "[DEBUG] Sync mode: $SYNC_MODE, Window: ${SYNC_START}:00 - ${SYNC_END}:00"

# Check if we should run
HOUR=$(date +%H)
HOUR_NUM=$((10#$HOUR))  # Force decimal interpretation

log "[DEBUG] Current hour: $HOUR_NUM, Mode: $SYNC_MODE"

if [ "$1" != "--force" ] && [ "$SYNC_MODE" != "24hr" ]; then
    # Check if we're in the sync window
    # For overnight windows (e.g., 22:00 to 06:00), hour must be >= start OR < end
    # For daytime windows (e.g., 09:00 to 17:00), hour must be >= start AND < end
    IN_WINDOW=0

    if [ "$SYNC_START" -gt "$SYNC_END" ]; then
        # Overnight window (e.g., 22 to 6)
        if [ "$HOUR_NUM" -ge "$SYNC_START" ] || [ "$HOUR_NUM" -lt "$SYNC_END" ]; then
            IN_WINDOW=1
        fi
    else
        # Daytime window (e.g., 9 to 17)
        if [ "$HOUR_NUM" -ge "$SYNC_START" ] && [ "$HOUR_NUM" -lt "$SYNC_END" ]; then
            IN_WINDOW=1
        fi
    fi

    log "[DEBUG] In sync window: $IN_WINDOW (hour=$HOUR_NUM, start=$SYNC_START, end=$SYNC_END)"

    if [ "$IN_WINDOW" -eq 0 ]; then
        log "[DEBUG] Outside sync window. Sync will resume at ${SYNC_START}:00"
        exit 0
    fi
fi

log "[DEBUG] Sync check passed - proceeding with backup"

log "=========================================="
log "Starting Google Drive backup"
log "Destination: $GDRIVE_DEST"

# Check prerequisites
if [ ! -f "$RCLONE_CONFIG" ]; then
    log "ERROR: rclone not configured"
    update_sync_status false
    exit 1
fi

if ! mountpoint -q "/media/external-hdd"; then
    log "ERROR: External HDD not mounted"
    update_sync_status false
    exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
    log "ERROR: Incoming folder not found"
    update_sync_status false
    exit 1
fi

# Check internet by testing rclone connection (ping may be blocked on some networks)
if ! rclone about gdrive: --config "$RCLONE_CONFIG" &> /dev/null; then
    log "ERROR: Cannot connect to Google Drive"
    update_sync_status false
    exit 1
fi

# Count local files
LOCAL_COUNT=$(find "$SOURCE_DIR" -type f 2>/dev/null | wc -l)
log "Local files to sync: $LOCAL_COUNT"

# Mark sync as active
update_sync_status true 0 0 "$LOCAL_COUNT" "Starting..."

# Function to check progress by counting cloud files
check_progress() {
    LAST_BYTES=0
    LAST_TIME=$(date +%s)
    while true; do
        sleep 5
        # Get cloud file count
        CLOUD_DATA=$(rclone size "$GDRIVE_DEST" --config "$RCLONE_CONFIG" --json 2>/dev/null)
        if [ -n "$CLOUD_DATA" ]; then
            CLOUD_COUNT=$(echo "$CLOUD_DATA" | jq -r '.count // 0')
            CLOUD_BYTES=$(echo "$CLOUD_DATA" | jq -r '.bytes // 0')
            CURRENT_TIME=$(date +%s)

            # Calculate speed in Mbps
            TIME_DIFF=$((CURRENT_TIME - LAST_TIME))
            if [ "$TIME_DIFF" -gt 0 ] && [ "$LAST_BYTES" -gt 0 ]; then
                BYTES_DIFF=$((CLOUD_BYTES - LAST_BYTES))
                # Convert to Mbps (bytes/sec * 8 / 1000000)
                SPEED_MBPS=$(echo "scale=1; $BYTES_DIFF * 8 / $TIME_DIFF / 1000000" | bc 2>/dev/null || echo "0")
                SPEED_TEXT="${SPEED_MBPS} Mbps"
            else
                SPEED_TEXT="calculating..."
            fi

            LAST_BYTES=$CLOUD_BYTES
            LAST_TIME=$CURRENT_TIME

            if [ "$LOCAL_COUNT" -gt 0 ]; then
                PCT=$((CLOUD_COUNT * 100 / LOCAL_COUNT))
                REMAINING=$((LOCAL_COUNT - CLOUD_COUNT))
                update_sync_status true "$PCT" "$CLOUD_COUNT" "$REMAINING" "$SPEED_TEXT"
            fi
        fi
        # Check if rclone is still running
        pgrep -f "rclone sync.*$GDRIVE_DEST" > /dev/null || break
    done
}

# Start progress checker in background
check_progress &
PROGRESS_PID=$!

# Run rclone sync
rclone sync "$SOURCE_DIR" "$GDRIVE_DEST" \
    --config "$RCLONE_CONFIG" \
    --bwlimit "$BANDWIDTH_LIMIT" \
    --transfers 4 \
    --checkers 8 \
    --exclude ".Trash-*/**" \
    --exclude ".lost+found/**" \
    --exclude "*.tmp" \
    --exclude "*.partial" \
    2>&1 | tee -a "$LOG_FILE"

SYNC_EXIT=${PIPESTATUS[0]}

# Kill progress checker
kill $PROGRESS_PID 2>/dev/null

if [ $SYNC_EXIT -eq 0 ]; then
    log "Backup completed successfully!"

    # Get final counts
    CLOUD_COUNT=$(rclone size "$GDRIVE_DEST" --config "$RCLONE_CONFIG" --json 2>/dev/null | jq -r '.count // 0')
    CLOUD_SIZE=$(rclone size "$GDRIVE_DEST" --config "$RCLONE_CONFIG" --json 2>/dev/null | jq -r '.bytes // 0')
    CLOUD_SIZE_HUMAN=$(numfmt --to=iec-i --suffix=B "$CLOUD_SIZE" 2>/dev/null || echo "$CLOUD_SIZE bytes")

    log "Cloud files: $CLOUD_COUNT ($CLOUD_SIZE_HUMAN)"

    # Update final status
    cat > "$SYNC_STATUS_FILE" << EOF
{
    "active": false,
    "percent": 100,
    "files_synced": $CLOUD_COUNT,
    "files_remaining": 0,
    "speed": "--",
    "total_files": $CLOUD_COUNT,
    "total_size": "$CLOUD_SIZE_HUMAN",
    "folder": "${DEVICE_NAME}-Sync/${TODAY}",
    "last_sync": "$(date '+%Y-%m-%d %H:%M')",
    "timestamp": "$(date -Iseconds)"
}
EOF
else
    log "ERROR: Backup failed with exit code $SYNC_EXIT"
    update_sync_status false 0 0 0 "Failed"
fi

log "=========================================="
