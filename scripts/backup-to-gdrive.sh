#!/bin/bash
# Google Drive Backup with Progress Reporting
# Supports 24hr mode (always sync) or scheduled window

SOURCE_DIR="/media/external-hdd"
LOG_FILE="/var/log/usb-transfer/gdrive-backup.log"
SYNC_STATUS_FILE="/tmp/gdrive-sync-status.json"
SYNC_CONFIG_FILE="/opt/usb-transfer/sync-config.json"
BANDWIDTH_LIMIT="10M"
RCLONE_CONFIG="/home/pebl/.config/rclone/rclone.conf"

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

log "Sync mode: $SYNC_MODE, Window: ${SYNC_START}:00 - ${SYNC_END}:00"

# Check if we should run
HOUR=$(date +%H)
if [ "$1" != "--force" ] && [ "$SYNC_MODE" != "24hr" ]; then
    # In scheduled mode, check the time window
    if [ "$HOUR" -lt "$SYNC_START" ] && [ "$HOUR" -ge "$SYNC_END" ]; then
        log "Outside sync window. Use --force to override."
        exit 0
    fi
fi

log "=========================================="
log "Starting Google Drive backup"
log "Destination: $GDRIVE_DEST"

# Check prerequisites
if [ ! -f "$RCLONE_CONFIG" ]; then
    log "ERROR: rclone not configured"
    update_sync_status false
    exit 1
fi

if ! mountpoint -q "$SOURCE_DIR"; then
    log "ERROR: External HDD not mounted"
    update_sync_status false
    exit 1
fi

if ! ping -c 1 google.com &> /dev/null; then
    log "ERROR: No internet connection"
    update_sync_status false
    exit 1
fi

# Count local files
LOCAL_COUNT=$(find "$SOURCE_DIR" -type f 2>/dev/null | wc -l)
log "Local files to sync: $LOCAL_COUNT"

# Mark sync as active
update_sync_status true 0 0 "$LOCAL_COUNT" "Starting..."

# Run rclone with progress output
rclone sync "$SOURCE_DIR" "$GDRIVE_DEST" \
    --config "$RCLONE_CONFIG" \
    --bwlimit "$BANDWIDTH_LIMIT" \
    --progress \
    --stats 2s \
    --stats-one-line \
    --transfers 4 \
    --checkers 8 \
    --exclude ".Trash-*/**" \
    --exclude ".lost+found/**" \
    --exclude "*.tmp" \
    --exclude "*.partial" \
    2>&1 | while IFS= read -r line; do
        echo "$line" >> "$LOG_FILE"

        # Parse rclone stats line
        if [[ "$line" =~ Transferred:.+([0-9]+)% ]]; then
            PCT="${BASH_REMATCH[1]}"
            SPEED=$(echo "$line" | grep -oP '\d+\.\d+\s*[KMG]i?B/s' | tail -1)
            SYNCED=$((LOCAL_COUNT * PCT / 100))
            REMAINING=$((LOCAL_COUNT - SYNCED))
            update_sync_status true "$PCT" "$SYNCED" "$REMAINING" "${SPEED:-calculating...}"
        fi
    done

SYNC_EXIT=${PIPESTATUS[0]}

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
