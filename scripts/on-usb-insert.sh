#!/bin/bash
# USB Auto-Transfer Script with Progress Reporting
# Triggered by udev when USB drive is inserted

DEVICE="/dev/$1"
LABEL="${2:-USB_DRIVE}"
MOUNT_POINT="/media/usb-source"
DEST_DIR="/media/external-hdd/incoming"
LOG_FILE="/var/log/usb-transfer/transfer.log"
STATUS_FILE="/tmp/usb-transfer-status"
PROGRESS_FILE="/tmp/usb-transfer-progress.json"
DECISION_FILE="/tmp/usb-transfer-decision"
LOCK_FILE="/tmp/usb-transfer.lock"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Update progress JSON
update_progress() {
    local pct="$1"
    local files_done="$2"
    local files_total="$3"
    local speed="$4"
    local eta="$5"
    local file_types="$6"
    local status="$7"
    local existing="${8:-0}"
    local message="${9:-}"
    local current_file="${10:-}"

    cat > "$PROGRESS_FILE" << EOF
{
    "percent": $pct,
    "files_done": $files_done,
    "files_total": $files_total,
    "speed": "$speed",
    "eta": "$eta",
    "file_types": ${file_types:-{}},
    "status": "${status:-transferring}",
    "existing_files": $existing,
    "message": "$message",
    "current_file": "$current_file",
    "timestamp": "$(date -Iseconds)"
}
EOF
    chmod 644 "$PROGRESS_FILE" 2>/dev/null
}

# Count files by extension (safe JSON output)
get_file_types() {
    local dir="$1"
    # Get extensions only (filter out paths and weird entries), limit to alphanumeric extensions
    local types=$(find "$dir" -type f -name "*.*" 2>/dev/null | \
        sed 's/.*\.//' | \
        grep -E '^[a-zA-Z0-9]{1,10}$' | \
        sort | uniq -c | sort -rn | head -5 | \
        awk 'BEGIN{printf "{"} NR>1{printf ","} {gsub(/^ +/,"",$1); printf "\"%s\": %s", $2, $1} END{printf "}"}')
    # Ensure valid JSON even if empty
    if [ -z "$types" ] || [ "$types" = "{}" ]; then
        echo "{}"
    else
        echo "$types"
    fi
}

# Check for existing files
check_existing_files() {
    local source_dir="$1"
    local dest_base="$2"
    local count=0

    while IFS= read -r -d '' file; do
        local filename=$(basename "$file")
        if find "$dest_base" -name "$filename" -type f 2>/dev/null | grep -q .; then
            ((count++))
        fi
    done < <(find "$source_dir" -type f -print0 2>/dev/null)

    echo "$count"
}

# ============================================
# IMMEDIATE FEEDBACK
# ============================================
log "=========================================="
log "USB DETECTED: $DEVICE (Label: $LABEL)"

# Write initial status immediately
echo "DETECTING" > "$STATUS_FILE"
chmod 644 "$STATUS_FILE" 2>/dev/null
update_progress 0 0 0 "--" "--" "{}" "detecting" 0 "USB drive detected, initializing..."

# Prevent multiple instances
if [ -f "$LOCK_FILE" ]; then
    log "Transfer already in progress. Exiting."
    exit 1
fi
touch "$LOCK_FILE"

# Cleanup function
cleanup() {
    rm -f "$LOCK_FILE"
    rm -f "$DECISION_FILE"
}
trap cleanup EXIT

# Update status - mounting
echo "MOUNTING" > "$STATUS_FILE"
update_progress 0 0 0 "--" "--" "{}" "mounting" 0 "USB detected: $LABEL - Waiting for device..."
log "Waiting for USB to be ready..."
log "Running as user: $(whoami), UID: $(id -u)"
log "Device: $DEVICE, Label: $LABEL"

# Check if device exists
if [ ! -b "$DEVICE" ]; then
    log "WARNING: Device $DEVICE does not exist yet, waiting..."
    update_progress 0 0 0 "--" "--" "{}" "mounting" 0 "Waiting for device $DEVICE..."
fi

# Wait for device to settle (systemd-run gives us more time)
for i in 1 2 3 4 5 6 7 8; do
    if [ -b "$DEVICE" ]; then
        log "Device $DEVICE exists (check $i)"
        break
    fi
    update_progress 0 0 0 "--" "--" "{}" "mounting" 0 "Waiting for device... ($i/8)"
    sleep 1
done

# Final wait for filesystem to be ready
sleep 2

# Check if already mounted by system - try multiple methods
EXISTING_MOUNT=""

# Method 1: Check lsblk
EXISTING_MOUNT=$(lsblk -no MOUNTPOINT "$DEVICE" 2>/dev/null | grep -v "^$" | head -1)
log "lsblk check: '$EXISTING_MOUNT'"

# Method 2: Check /media/pebl for any new mounts
if [ -z "$EXISTING_MOUNT" ]; then
    for dir in /media/pebl/*; do
        if [ -d "$dir" ]; then
            # Check if this directory has files (is mounted)
            if [ "$(ls -A "$dir" 2>/dev/null)" ]; then
                EXISTING_MOUNT="$dir"
                log "Found mount at: $EXISTING_MOUNT"
                break
            fi
        fi
    done
fi

# Method 3: Check findmnt
if [ -z "$EXISTING_MOUNT" ]; then
    EXISTING_MOUNT=$(findmnt -no TARGET "$DEVICE" 2>/dev/null | head -1)
    log "findmnt check: '$EXISTING_MOUNT'"
fi

if [ -n "$EXISTING_MOUNT" ]; then
    log "Using existing mount at: $EXISTING_MOUNT"
    MOUNT_POINT="$EXISTING_MOUNT"
else
    # Try to mount ourselves with retry logic
    mkdir -p "$MOUNT_POINT"

    MOUNT_SUCCESS=0
    for attempt in 1 2 3 4 5; do
        log "Mount attempt $attempt of 5 for $DEVICE to $MOUNT_POINT"
        update_progress 0 0 0 "--" "--" "{}" "mounting" 0 "Mounting $LABEL (attempt $attempt/5)..."

        # Check device exists
        if [ ! -b "$DEVICE" ]; then
            log "Device $DEVICE not ready yet"
            sleep 2
            continue
        fi

        # Get filesystem type
        FSTYPE=$(blkid -o value -s TYPE "$DEVICE" 2>/dev/null)
        log "Filesystem type: $FSTYPE"

        # Capture mount output without pipe (pipe breaks exit code)
        MOUNT_OUTPUT=$(mount "$DEVICE" "$MOUNT_POINT" 2>&1)
        MOUNT_EXIT=$?

        if [ $MOUNT_EXIT -eq 0 ]; then
            log "Mount successful on attempt $attempt"
            MOUNT_SUCCESS=1
            break
        else
            log "Mount attempt $attempt failed (exit $MOUNT_EXIT): $MOUNT_OUTPUT"
            update_progress 0 0 0 "--" "--" "{}" "mounting" 0 "Mount attempt $attempt failed, retrying..."
            if [ $attempt -lt 5 ]; then
                sleep 2
            fi
        fi
    done

    if [ $MOUNT_SUCCESS -eq 0 ]; then
        log "ERROR: Failed to mount $DEVICE after 5 attempts"
        log "Last error: $MOUNT_OUTPUT"
        echo "FAILED" > "$STATUS_FILE"
        update_progress 0 0 0 "--" "--" "{}" "failed" 0 "Mount failed: $MOUNT_OUTPUT"
        /opt/usb-transfer/notify-user.sh "Mount Failed" "Could not mount USB drive $LABEL"
        exit 1
    fi
fi

# Verify mount has files
if [ ! "$(ls -A "$MOUNT_POINT" 2>/dev/null)" ]; then
    log "ERROR: Mount point is empty or not accessible"
    echo "FAILED" > "$STATUS_FILE"
    update_progress 0 0 0 "--" "--" "{}" "failed" 0 "USB drive is empty or not readable"
    exit 1
fi

log "USB mounted successfully at $MOUNT_POINT"

# Update status - scanning
echo "SCANNING" > "$STATUS_FILE"
update_progress 0 0 0 "--" "--" "{}" "scanning" 0 "Scanning USB drive for files..."
log "Scanning USB drive..."

# Check if external HDD is mounted
if ! mountpoint -q /media/external-hdd; then
    log "ERROR: External HDD not mounted at /media/external-hdd"
    echo "FAILED" > "$STATUS_FILE"
    update_progress 0 0 0 "--" "--" "{}" "failed" 0 "External HDD not connected"
    /opt/usb-transfer/notify-user.sh "HDD Not Found" "External hard drive is not connected"
    exit 1
fi

# Calculate totals
TOTAL_SIZE=$(du -sh "$MOUNT_POINT" 2>/dev/null | cut -f1)
FILE_COUNT=$(find "$MOUNT_POINT" -type f 2>/dev/null | wc -l)
FILE_TYPES=$(get_file_types "$MOUNT_POINT")

log "Found $FILE_COUNT files ($TOTAL_SIZE)"
update_progress 0 0 "$FILE_COUNT" "--" "--" "$FILE_TYPES" "scanning" 0 "Found $FILE_COUNT files ($TOTAL_SIZE)"

# Check for existing files
log "Checking for existing files on HDD..."
echo "CHECKING" > "$STATUS_FILE"
update_progress 0 0 "$FILE_COUNT" "--" "--" "$FILE_TYPES" "checking" 0 "Checking for duplicate files..."

EXISTING_COUNT=$(check_existing_files "$MOUNT_POINT" "$DEST_DIR")
log "Found $EXISTING_COUNT files that already exist on HDD (out of $FILE_COUNT total)"

# Update UI with duplicate count
update_progress 0 0 "$FILE_COUNT" "--" "--" "$FILE_TYPES" "checking" "$EXISTING_COUNT" "Found $EXISTING_COUNT duplicates out of $FILE_COUNT files"

# Check if ALL files are duplicates
if [ "$EXISTING_COUNT" -eq "$FILE_COUNT" ] && [ "$FILE_COUNT" -gt 0 ]; then
    log "All $FILE_COUNT files already exist on HDD - nothing to transfer"
    echo "ALL_DUPLICATES" > "$STATUS_FILE"
    update_progress 100 "$FILE_COUNT" "$FILE_COUNT" "--" "--" "$FILE_TYPES" "all_duplicates" "$EXISTING_COUNT" "All $FILE_COUNT files already backed up"
    /opt/usb-transfer/notify-user.sh "Already Backed Up" "All $FILE_COUNT files from $LABEL already exist on HDD"
    log "=========================================="
    exit 0
fi

# If some existing files found, wait for user decision
DECISION="overwrite"
NEW_FILES=$((FILE_COUNT - EXISTING_COUNT))
if [ "$EXISTING_COUNT" -gt 0 ]; then
    log "Waiting for user decision (skip/overwrite)... $NEW_FILES new files, $EXISTING_COUNT duplicates"
    echo "PENDING_DECISION" > "$STATUS_FILE"
    update_progress 0 0 "$FILE_COUNT" "--" "--" "$FILE_TYPES" "pending" "$EXISTING_COUNT" "$NEW_FILES new files, $EXISTING_COUNT already exist"

    rm -f "$DECISION_FILE"

    TIMEOUT=300
    ELAPSED=0
    while [ ! -f "$DECISION_FILE" ] && [ $ELAPSED -lt $TIMEOUT ]; do
        sleep 1
        ((ELAPSED++))
    done

    if [ ! -f "$DECISION_FILE" ]; then
        log "Timeout waiting for user decision. Defaulting to skip."
        DECISION="skip"
    else
        DECISION=$(cat "$DECISION_FILE")
    fi

    log "User decision: $DECISION"
fi

# Create destination folder with timestamp
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
DEST_FOLDER="$DEST_DIR/${LABEL}_${TIMESTAMP}"
mkdir -p "$DEST_FOLDER"

log "Starting transfer: $TOTAL_SIZE ($FILE_COUNT files) to $DEST_FOLDER"

# Update status - transferring
echo "TRANSFERRING" > "$STATUS_FILE"
update_progress 0 0 "$FILE_COUNT" "Starting..." "--" "$FILE_TYPES" "transferring" 0 "Starting file transfer..."
/opt/usb-transfer/notify-user.sh "Transfer Started" "Copying $TOTAL_SIZE from $LABEL..."

# Build rsync options
RSYNC_OPTS="-avh --progress --info=progress2"
if [ "$DECISION" = "skip" ]; then
    RSYNC_OPTS="$RSYNC_OPTS --ignore-existing"
    log "Using skip mode (--ignore-existing)"
fi

# Transfer with rsync - capture current file
LAST_UPDATE=0
CURRENT_FILE=""
rsync $RSYNC_OPTS "$MOUNT_POINT/" "$DEST_FOLDER/" 2>&1 | \
while IFS= read -r line; do
    echo "$line" >> "$LOG_FILE"

    # Capture filename (lines that don't start with space are filenames)
    if [[ ! "$line" =~ ^[[:space:]] ]] && [[ ! "$line" =~ ^sent ]] && [[ ! "$line" =~ ^total ]] && [[ ! "$line" =~ ^rsync ]]; then
        CURRENT_FILE="$line"
    fi

    if [[ "$line" =~ ([0-9]+)% ]]; then
        PCT="${BASH_REMATCH[1]}"
        NOW=$(date +%s)

        if [ $((NOW - LAST_UPDATE)) -ge 1 ]; then
            LAST_UPDATE=$NOW
            SPEED=$(echo "$line" | grep -oP '\d+\.\d+[KMG]B/s' | tail -1)
            ETA=$(echo "$line" | grep -oP '\d+:\d+:\d+' | tail -1)
            FILES_DONE=$((FILE_COUNT * PCT / 100))

            # Truncate filename for display
            DISPLAY_FILE="${CURRENT_FILE:0:40}"
            if [ ${#CURRENT_FILE} -gt 40 ]; then
                DISPLAY_FILE="${DISPLAY_FILE}..."
            fi

            update_progress "$PCT" "$FILES_DONE" "$FILE_COUNT" "${SPEED:-calculating...}" "${ETA:---}" "$FILE_TYPES" "transferring" 0 "Copying: $DISPLAY_FILE ($PCT%)" "$CURRENT_FILE"
        fi
    fi
done

RSYNC_EXIT=${PIPESTATUS[0]}

# rsync exit code 23 = partial transfer (some files had errors but others succeeded)
if [ $RSYNC_EXIT -eq 0 ] || [ $RSYNC_EXIT -eq 23 ]; then
    log "Transfer completed!"
    echo "COMPLETE" > "$STATUS_FILE"

    TRANSFERRED_COUNT=$(find "$DEST_FOLDER" -type f 2>/dev/null | wc -l)
    log "Verified: $TRANSFERRED_COUNT files transferred"

    update_progress 100 "$TRANSFERRED_COUNT" "$FILE_COUNT" "Done" "0:00:00" "$FILE_TYPES" "complete" 0 "Transfer complete! $TRANSFERRED_COUNT files copied"

    sync
    log "Transfer complete. Safe to remove USB."
    /opt/usb-transfer/notify-user.sh "Transfer Complete" "Safe to remove USB ($LABEL). Transferred: $TOTAL_SIZE ($TRANSFERRED_COUNT files)"
else
    log "ERROR: Transfer failed with exit code $RSYNC_EXIT"
    echo "FAILED" > "$STATUS_FILE"
    update_progress 0 0 "$FILE_COUNT" "--" "--" "$FILE_TYPES" "failed" 0 "Transfer failed (error code $RSYNC_EXIT)"
    /opt/usb-transfer/notify-user.sh "Transfer Failed" "Error copying from $LABEL. Check logs."
fi

log "=========================================="
