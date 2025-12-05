#!/bin/bash
# Multi-method notification script

TITLE="$1"
MESSAGE="$2"
LOG_FILE="/var/log/usb-transfer/notifications.log"

# Log notification
echo "$(date '+%Y-%m-%d %H:%M:%S') - [$TITLE] $MESSAGE" >> "$LOG_FILE"

# Method 1: Console broadcast to all terminals
wall "USB Transfer: $TITLE - $MESSAGE" 2>/dev/null

# Method 2: Desktop notification (if X display available)
if [ -n "$DISPLAY" ]; then
    notify-send "USB Transfer: $TITLE" "$MESSAGE" 2>/dev/null
fi

# Method 3: Play sound (beep pattern)
# Success = 2 short beeps, Error = 3 long beeps
if [[ "$TITLE" == *"Complete"* ]] || [[ "$TITLE" == *"Started"* ]]; then
    for i in 1 2; do
        echo -e "\a" > /dev/console 2>/dev/null
        sleep 0.2
    done
elif [[ "$TITLE" == *"Failed"* ]] || [[ "$TITLE" == *"Error"* ]]; then
    for i in 1 2 3; do
        echo -e "\a" > /dev/console 2>/dev/null
        sleep 0.5
    done
fi

# Method 4: GPIO LED indicator (if wiringPi available)
# GPIO 17 = Status LED
if command -v gpio &> /dev/null; then
    gpio -g mode 17 out
    if [[ "$TITLE" == *"Complete"* ]]; then
        # Solid on for success
        gpio -g write 17 1
    elif [[ "$TITLE" == *"Failed"* ]]; then
        # Rapid blink for error
        for i in {1..10}; do
            gpio -g write 17 1; sleep 0.1
            gpio -g write 17 0; sleep 0.1
        done
    elif [[ "$TITLE" == *"Started"* ]] || [[ "$TITLE" == *"TRANSFERRING"* ]]; then
        # Slow blink during transfer (handled by status-monitor service)
        gpio -g write 17 1
    fi
fi

# Method 5: Write to JSON log for web dashboard
JSON_LOG="/var/log/usb-transfer/notifications.json"
echo "{\"time\": \"$(date -Iseconds)\", \"title\": \"$TITLE\", \"message\": \"$MESSAGE\"}" >> "$JSON_LOG"

# Method 6: Write to LCD display file (for I2C LCD screens)
echo -e "$TITLE\n$MESSAGE" > /tmp/lcd-message 2>/dev/null
