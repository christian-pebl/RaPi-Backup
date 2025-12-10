#!/usr/bin/env python3
"""
PEBL USB Transfer Monitor - Light Theme
Touch-optimized for 7-inch display
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk, GdkPixbuf
import os
import json
import subprocess
import threading
from datetime import datetime, timedelta

STATUS_FILE = "/tmp/usb-transfer-status"
PROGRESS_FILE = "/tmp/usb-transfer-progress.json"
SYNC_STATUS_FILE = "/tmp/gdrive-sync-status.json"
SYNC_CONFIG_FILE = "/opt/usb-transfer/sync-config.json"
DECISION_FILE = "/tmp/usb-transfer-decision"
DEVICE_REF_FILE = "/tmp/usb-device-reference"
LOGO_PATH = "/opt/usb-transfer/assets/pebl-logo.png"
RCLONE_CONFIG = "/home/pebl/.config/rclone/rclone.conf"
GDRIVE_INFO_FILE = "/tmp/gdrive-info.json"

# Screen brightness settings (auto-detected on init)
BACKLIGHT_BASE = "/sys/class/backlight"
AUTO_DIM_SECONDS = 300   # 5 minutes default

# Default sync settings
DEFAULT_CONFIG = {
    "mode": "24hr",
    "start_hour": 22,
    "end_hour": 6
}

CSS = b"""
window { background-color: #f5f5f5; }
.header { background-color: #ffffff; padding: 10px; }
.title { font-size: 24px; font-weight: bold; color: #333333; }
.time-label { font-size: 16px; color: #666666; }
.panel { background-color: #ffffff; border-radius: 12px; padding: 20px; margin: 8px; }
.section-title { font-size: 20px; font-weight: bold; color: #333333; margin-bottom: 10px; }
.status-text { font-size: 20px; color: #333333; }
.status-active { color: #2196F3; font-weight: bold; }
.status-complete { color: #4CAF50; font-weight: bold; }
.status-failed { color: #f44336; font-weight: bold; }
.status-pending { color: #FF9800; font-weight: bold; }
.info-text { font-size: 16px; color: #666666; }
.message-text { font-size: 14px; color: #888888; font-style: italic; }
.warning-text { font-size: 18px; color: #FF9800; font-weight: bold; }
.big-button { font-size: 18px; font-weight: bold; padding: 15px 30px; border-radius: 8px; min-height: 50px; border: none; }
.btn-primary { background-color: #2196F3; color: white; }
.btn-success { background-color: #4CAF50; color: white; }
.btn-warning { background-color: #FF9800; color: white; }
.btn-grey { background-color: #757575; color: white; }
.sync-info { font-size: 14px; color: #888888; }
.sync-active { color: #4CAF50; font-weight: bold; }
.sync-complete { font-size: 16px; color: #4CAF50; font-weight: bold; }
.mode-24hr { color: #FF9800; font-weight: bold; }
.current-file { font-size: 12px; color: #2196F3; font-family: monospace; }
progressbar { min-height: 24px; }
progressbar trough { min-height: 24px; background-color: #e0e0e0; border-radius: 12px; }
progressbar progress { min-height: 24px; background-color: #2196F3; border-radius: 12px; }
.minimize-btn { font-size: 20px; padding: 5px 15px; background-color: #e0e0e0; border-radius: 5px; border: none; }
.close-btn { font-size: 20px; padding: 5px 15px; background-color: #f44336; color: white; border-radius: 5px; border: none; }
.settings-btn { font-size: 14px; padding: 8px 15px; background-color: #e0e0e0; border-radius: 5px; }
.small-btn { font-size: 14px; padding: 8px 20px; border-radius: 5px; background-color: #bdbdbd; border: none; }
.dim-btn { font-size: 14px; padding: 8px 12px; background-color: #9e9e9e; color: white; border-radius: 5px; border: none; }
.dim-overlay { background-color: rgba(0, 0, 0, 0.95); }
"""


def load_config():
    if os.path.exists(SYNC_CONFIG_FILE):
        try:
            with open(SYNC_CONFIG_FILE) as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    try:
        with open(SYNC_CONFIG_FILE, 'w') as f:
            json.dump(config, f)
    except:
        pass


def fetch_gdrive_info():
    """Fetch Google Drive account info and storage stats (runs in background)"""
    try:
        # Get storage info from rclone
        result = subprocess.run(
            ["rclone", "about", "gdrive:", "--json"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)

            # Count files in incoming folder
            count_result = subprocess.run(
                ["bash", "-c", "find /media/external-hdd/incoming -type f 2>/dev/null | wc -l"],
                capture_output=True, text=True, timeout=60
            )
            local_count = 0
            if count_result.returncode == 0 and count_result.stdout.strip():
                try:
                    local_count = int(count_result.stdout.strip())
                except:
                    pass

            # Get incoming folder size
            size_result = subprocess.run(
                ["bash", "-c", "du -sb /media/external-hdd/incoming 2>/dev/null | cut -f1"],
                capture_output=True, text=True, timeout=120
            )
            local_size = 0
            if size_result.returncode == 0 and size_result.stdout.strip():
                try:
                    local_size = int(size_result.stdout.strip())
                except:
                    pass

            # Get cloud folder size (with longer timeout)
            cloud_result = subprocess.run(
                ["rclone", "size", "gdrive:RaPi-PEBL-Sync", "--json"],
                capture_output=True, text=True, timeout=180
            )
            cloud_count = 0
            cloud_size = 0
            if cloud_result.returncode == 0 and cloud_result.stdout:
                try:
                    cloud_data = json.loads(cloud_result.stdout)
                    cloud_count = cloud_data.get("count", 0)
                    cloud_size = cloud_data.get("bytes", 0)
                except:
                    pass

            # Calculate sync percentage based on file count (more accurate)
            sync_pct = 0
            if local_count > 0:
                sync_pct = min(100, int(cloud_count / local_count * 100))

            gdrive_info = {
                "total_bytes": info.get("total", 0),
                "used_bytes": info.get("used", 0),
                "free_bytes": info.get("free", 0),
                "local_files": local_count,
                "local_size": local_size,
                "cloud_files": cloud_count,
                "cloud_size": cloud_size,
                "sync_percent": sync_pct,
                "last_updated": datetime.now().isoformat()
            }

            with open(GDRIVE_INFO_FILE, 'w') as f:
                json.dump(gdrive_info, f)

    except Exception as e:
        pass  # Silently fail - info is optional


def format_bytes(size):
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


class PEBLTransferMonitor(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="PEBL Data Backup")
        self.set_default_size(800, 480)
        self.set_decorated(False)
        self.fullscreen()

        # Clear old status files on startup
        self.clear_old_status()

        self.config = load_config()
        self.apply_css()
        self.setup_ui()

        # Fetch Google Drive info in background
        self.gdrive_info = {}
        self.start_gdrive_info_fetch()

        # Screen dimming state
        self.is_dimmed = False
        self.last_activity_time = GLib.get_monotonic_time()
        self.dim_timer_id = None
        self.detect_backlight()
        self.start_auto_dim_timer()

    def clear_old_status(self):
        """Clear old status files so app starts fresh"""
        # Force remove with sudo to handle permissions
        subprocess.run(["sudo", "rm", "-f", STATUS_FILE, PROGRESS_FILE, "/tmp/usb-transfer.lock"], capture_output=True)

    def setup_ui(self):
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(self.main_box)

        self.create_header()

        self.content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.content.set_margin_start(10)
        self.content.set_margin_end(10)
        self.content.set_margin_bottom(10)
        self.main_box.pack_start(self.content, True, True, 0)

        self.create_transfer_panel()
        self.create_sync_panel()

        # Update more frequently for better responsiveness
        GLib.timeout_add(500, self.update_all)
        # Check for USB removal every 2 seconds
        GLib.timeout_add(2000, self.check_usb_removed)
        self.transfer_done = False
        self.decision_dialog_shown = False
        self.device_ref_dialog_shown = False
        self.last_status = ""

    def apply_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def create_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.get_style_context().add_class("header")
        header.set_margin_start(15)
        header.set_margin_end(15)
        header.set_margin_top(10)
        header.set_margin_bottom(5)

        if os.path.exists(LOGO_PATH):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(LOGO_PATH, 120, 40, True)
                logo = Gtk.Image.new_from_pixbuf(pixbuf)
                header.pack_start(logo, False, False, 0)
            except:
                pass

        title = Gtk.Label(label="Data Backup System")
        title.get_style_context().add_class("title")
        header.pack_start(title, False, False, 20)

        header.pack_start(Gtk.Box(), True, True, 0)

        self.time_label = Gtk.Label()
        self.time_label.get_style_context().add_class("time-label")
        header.pack_start(self.time_label, False, False, 10)

        settings_btn = Gtk.Button(label="Settings")
        settings_btn.get_style_context().add_class("settings-btn")
        settings_btn.connect("clicked", self.on_settings)
        header.pack_start(settings_btn, False, False, 5)

        dim_btn = Gtk.Button(label="Dim")
        dim_btn.get_style_context().add_class("dim-btn")
        dim_btn.connect("clicked", self.on_dim_screen)
        header.pack_start(dim_btn, False, False, 5)

        minimize_btn = Gtk.Button(label="_")
        minimize_btn.get_style_context().add_class("minimize-btn")
        minimize_btn.connect("clicked", self.on_minimize)
        header.pack_start(minimize_btn, False, False, 5)

        close_btn = Gtk.Button(label="X")
        close_btn.get_style_context().add_class("close-btn")
        close_btn.connect("clicked", self.on_close)
        header.pack_start(close_btn, False, False, 5)

        self.main_box.pack_start(header, False, False, 0)

    def create_transfer_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.get_style_context().add_class("panel")
        panel.set_size_request(420, -1)
        self.content.pack_start(panel, True, True, 5)

        section_title = Gtk.Label(label="USB Transfer")
        section_title.get_style_context().add_class("section-title")
        section_title.set_xalign(0)
        panel.pack_start(section_title, False, False, 5)

        # Status text - main message
        self.status_text = Gtk.Label(label="Insert USB drive to start backup")
        self.status_text.get_style_context().add_class("status-text")
        self.status_text.set_line_wrap(True)
        self.status_text.set_justify(Gtk.Justification.CENTER)
        panel.pack_start(self.status_text, False, False, 10)

        # Progress bar
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        self.progress.set_text("0%")
        self.progress.set_margin_start(20)
        self.progress.set_margin_end(20)
        panel.pack_start(self.progress, False, False, 5)

        # Detailed message - shows current action
        self.message_label = Gtk.Label(label="")
        self.message_label.get_style_context().add_class("message-text")
        self.message_label.set_line_wrap(True)
        panel.pack_start(self.message_label, False, False, 5)

        # File info
        self.file_info = Gtk.Label(label="")
        self.file_info.get_style_context().add_class("info-text")
        panel.pack_start(self.file_info, False, False, 0)

        # File types
        self.file_types = Gtk.Label(label="")
        self.file_types.get_style_context().add_class("info-text")
        panel.pack_start(self.file_types, False, False, 0)

        # Current file being transferred
        self.current_file_label = Gtk.Label(label="")
        self.current_file_label.get_style_context().add_class("current-file")
        self.current_file_label.set_line_wrap(True)
        self.current_file_label.set_max_width_chars(50)
        self.current_file_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        panel.pack_start(self.current_file_label, False, False, 2)

        # Speed/ETA
        self.speed_label = Gtk.Label(label="")
        self.speed_label.get_style_context().add_class("info-text")
        panel.pack_start(self.speed_label, False, False, 0)

        panel.pack_start(Gtk.Box(), True, True, 0)

        # Button box for Cancel, Eject, and Remount
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_box.set_halign(Gtk.Align.CENTER)

        # Cancel button - shown during transfer
        self.cancel_btn = Gtk.Button(label="Cancel")
        self.cancel_btn.get_style_context().add_class("big-button")
        self.cancel_btn.get_style_context().add_class("btn-warning")
        self.cancel_btn.connect("clicked", self.on_cancel)
        self.cancel_btn.set_sensitive(False)
        self.cancel_btn.set_no_show_all(True)
        btn_box.pack_start(self.cancel_btn, False, False, 0)

        # Eject button - styled like sync mode buttons
        self.eject_btn = Gtk.Button(label="Eject USB")
        self.eject_btn.get_style_context().add_class("small-btn")
        self.eject_btn.connect("clicked", self.on_eject)
        self.set_eject_button_state(False)
        btn_box.pack_start(self.eject_btn, False, False, 0)

        # Remount button - to rescan and mount USB devices
        self.remount_btn = Gtk.Button(label="Remount")
        self.remount_btn.get_style_context().add_class("small-btn")
        self.remount_btn.connect("clicked", self.on_remount)
        btn_box.pack_start(self.remount_btn, False, False, 0)

        panel.pack_start(btn_box, False, False, 10)

    def create_sync_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.get_style_context().add_class("panel")
        self.content.pack_start(panel, True, True, 5)

        section_title = Gtk.Label(label="Cloud Backup")
        section_title.get_style_context().add_class("section-title")
        section_title.set_xalign(0)
        panel.pack_start(section_title, False, False, 5)

        # Google Drive account/storage info
        self.gdrive_account_label = Gtk.Label(label="Google Drive: Connecting...")
        self.gdrive_account_label.get_style_context().add_class("info-text")
        self.gdrive_account_label.set_xalign(0)
        panel.pack_start(self.gdrive_account_label, False, False, 0)

        self.gdrive_storage_label = Gtk.Label(label="")
        self.gdrive_storage_label.get_style_context().add_class("sync-info")
        self.gdrive_storage_label.set_xalign(0)
        panel.pack_start(self.gdrive_storage_label, False, False, 0)

        # Separator
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        panel.pack_start(sep, False, False, 5)

        # Sync folder info
        self.sync_folder = Gtk.Label()
        self.sync_folder.get_style_context().add_class("info-text")
        self.sync_folder.set_xalign(0)
        panel.pack_start(self.sync_folder, False, False, 0)

        # Overall sync status (local vs cloud)
        self.sync_status_label = Gtk.Label(label="")
        self.sync_status_label.get_style_context().add_class("sync-info")
        self.sync_status_label.set_xalign(0)
        panel.pack_start(self.sync_status_label, False, False, 0)

        # Sync completion progress bar (overall)
        sync_pct_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        sync_pct_label = Gtk.Label(label="Synced:")
        sync_pct_label.get_style_context().add_class("sync-info")
        sync_pct_box.pack_start(sync_pct_label, False, False, 0)
        self.sync_pct_progress = Gtk.ProgressBar()
        self.sync_pct_progress.set_show_text(True)
        self.sync_pct_progress.set_text("--")
        self.sync_pct_progress.set_hexpand(True)
        sync_pct_box.pack_start(self.sync_pct_progress, True, True, 0)
        panel.pack_start(sync_pct_box, False, False, 5)

        # Separator
        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        panel.pack_start(sep2, False, False, 5)

        # Current sync activity
        self.sync_mode_label = Gtk.Label()
        self.sync_mode_label.get_style_context().add_class("sync-info")
        panel.pack_start(self.sync_mode_label, False, False, 0)

        self.sync_schedule = Gtk.Label()
        self.sync_schedule.get_style_context().add_class("sync-info")
        panel.pack_start(self.sync_schedule, False, False, 0)

        # Upload speed and last sync info
        self.sync_stats = Gtk.Label(label="")
        self.sync_stats.get_style_context().add_class("info-text")
        panel.pack_start(self.sync_stats, False, False, 0)

        panel.pack_start(Gtk.Box(), True, True, 0)

        # Sync mode buttons
        mode_label = Gtk.Label(label="Sync Schedule:")
        mode_label.get_style_context().add_class("info-text")
        mode_label.set_xalign(0)
        panel.pack_start(mode_label, False, False, 5)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mode_box.set_halign(Gtk.Align.CENTER)

        self.btn_24hr = Gtk.Button(label="24hr")
        self.btn_24hr.get_style_context().add_class("small-btn")
        self.btn_24hr.connect("clicked", self.on_sync_mode_24hr)
        mode_box.pack_start(self.btn_24hr, False, False, 0)

        self.btn_night = Gtk.Button(label="Night")
        self.btn_night.get_style_context().add_class("small-btn")
        self.btn_night.connect("clicked", self.on_sync_mode_night)
        mode_box.pack_start(self.btn_night, False, False, 0)

        self.btn_custom = Gtk.Button(label="Custom")
        self.btn_custom.get_style_context().add_class("small-btn")
        self.btn_custom.connect("clicked", self.on_sync_mode_custom)
        mode_box.pack_start(self.btn_custom, False, False, 0)

        panel.pack_start(mode_box, False, False, 5)

        # Dismount All button - for safe shutdown
        self.dismount_btn = Gtk.Button(label="Shutdown & Store")
        self.dismount_btn.get_style_context().add_class("small-btn")
        self.dismount_btn.connect("clicked", self.on_dismount_all)
        panel.pack_start(self.dismount_btn, False, False, 10)

        # Update button styles based on current mode
        self.update_sync_mode_buttons()

    def on_minimize(self, btn):
        self.unfullscreen()
        self.iconify()

    def on_close(self, btn):
        Gtk.main_quit()

    # ============================================
    # SCREEN BRIGHTNESS CONTROL
    # ============================================
    def detect_backlight(self):
        """Auto-detect backlight device and max brightness"""
        self.backlight_path = None
        self.brightness_max = 255
        self.brightness_dim = 5

        try:
            # Find first backlight device
            if os.path.exists(BACKLIGHT_BASE):
                devices = os.listdir(BACKLIGHT_BASE)
                if devices:
                    device = devices[0]
                    self.backlight_path = f"{BACKLIGHT_BASE}/{device}/brightness"

                    # Read max brightness
                    max_path = f"{BACKLIGHT_BASE}/{device}/max_brightness"
                    if os.path.exists(max_path):
                        with open(max_path) as f:
                            self.brightness_max = int(f.read().strip())
                            # Set dim to ~10% of max
                            self.brightness_dim = max(1, self.brightness_max // 10)
        except Exception as e:
            pass

    def set_brightness(self, level):
        """Set screen brightness"""
        if not self.backlight_path:
            return

        try:
            subprocess.run(
                ["sudo", "sh", "-c", f"echo {level} > {self.backlight_path}"],
                capture_output=True, timeout=5
            )
        except:
            # Fallback: try without sudo
            try:
                with open(self.backlight_path, 'w') as f:
                    f.write(str(level))
            except:
                pass

    def dim_screen(self):
        """Dim the screen to low brightness"""
        if not self.is_dimmed:
            self.is_dimmed = True
            self.set_brightness(self.brightness_dim)

    def wake_screen(self):
        """Wake the screen to full brightness"""
        if self.is_dimmed:
            self.is_dimmed = False
            self.set_brightness(self.brightness_max)
        # Reset activity timer
        self.last_activity_time = GLib.get_monotonic_time()

    def on_dim_screen(self, btn):
        """Handler for dim button click"""
        self.dim_screen()

    def on_activity(self, widget, event):
        """Called on any user interaction to wake screen and reset timer"""
        self.wake_screen()
        return False  # Allow event to propagate

    def start_auto_dim_timer(self):
        """Start the auto-dim timer that checks every 10 seconds"""
        if self.dim_timer_id:
            GLib.source_remove(self.dim_timer_id)
        self.dim_timer_id = GLib.timeout_add(10000, self.check_auto_dim)

        # Connect motion/button events to wake screen
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK |
                       Gdk.EventMask.BUTTON_PRESS_MASK |
                       Gdk.EventMask.TOUCH_MASK)
        self.connect("motion-notify-event", self.on_activity)
        self.connect("button-press-event", self.on_activity)

    def check_auto_dim(self):
        """Check if screen should auto-dim due to inactivity"""
        if not self.is_dimmed:
            current_time = GLib.get_monotonic_time()
            elapsed_seconds = (current_time - self.last_activity_time) / 1000000  # Convert microseconds
            if elapsed_seconds >= AUTO_DIM_SECONDS:
                self.dim_screen()
        return True  # Keep timer running

    def update_sync_mode_buttons(self):
        """Update button styles to show active mode"""
        mode = self.config.get("mode", "24hr")

        # Reset all buttons to default style
        for btn in [self.btn_24hr, self.btn_night, self.btn_custom]:
            btn.get_style_context().remove_class("btn-primary")
            btn.get_style_context().add_class("small-btn")

        # Highlight active mode
        if mode == "24hr":
            self.btn_24hr.get_style_context().add_class("btn-primary")
        elif mode == "night":
            self.btn_night.get_style_context().add_class("btn-primary")
        else:  # scheduled/custom
            self.btn_custom.get_style_context().add_class("btn-primary")

    def is_in_sync_window(self, start_hour, end_hour):
        """Check if current time is within the sync window"""
        hour = datetime.now().hour
        if start_hour > end_hour:
            # Overnight window (e.g., 22 to 6)
            return hour >= start_hour or hour < end_hour
        else:
            # Daytime window (e.g., 9 to 17)
            return hour >= start_hour and hour < end_hour

    def stop_running_sync(self):
        """Stop any running sync process"""
        subprocess.run(["pkill", "-f", "backup-to-gdrive"], capture_output=True)
        subprocess.run(["pkill", "-f", "rclone sync"], capture_output=True)
        # Clear the sync lock file
        subprocess.run(["rm", "-f", "/tmp/gdrive-sync.lock"], capture_output=True)

    def apply_sync_mode_change(self):
        """Apply sync mode change - stop sync if now outside window"""
        mode = self.config.get("mode", "24hr")
        if mode == "24hr":
            # 24hr mode - sync should continue
            return

        start = self.config.get("start_hour", 22)
        end = self.config.get("end_hour", 6)

        if not self.is_in_sync_window(start, end):
            # Outside sync window - stop any running sync
            self.stop_running_sync()

    def on_sync_mode_24hr(self, btn):
        """Set 24hr sync mode (always on)"""
        self.config["mode"] = "24hr"
        save_config(self.config)
        self.update_sync_mode_buttons()
        # No need to stop sync - 24hr mode allows continuous sync

    def on_sync_mode_night(self, btn):
        """Set night sync mode (10pm - 6am)"""
        self.config["mode"] = "night"
        self.config["start_hour"] = 22
        self.config["end_hour"] = 6
        save_config(self.config)
        self.update_sync_mode_buttons()
        self.apply_sync_mode_change()

    def on_sync_mode_custom(self, btn):
        """Show custom time picker dialog"""
        dialog = Gtk.Dialog(title="Custom Sync Schedule", transient_for=self, modal=True)
        dialog.set_default_size(300, 200)
        box = dialog.get_content_area()
        box.set_spacing(15)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)

        # Start time
        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        start_box.pack_start(Gtk.Label(label="Start time:"), False, False, 0)
        start_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        start_spin.set_value(self.config.get("start_hour", 22))
        start_box.pack_start(start_spin, False, False, 0)
        start_box.pack_start(Gtk.Label(label=":00"), False, False, 0)
        box.pack_start(start_box, False, False, 0)

        # End time
        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        end_box.pack_start(Gtk.Label(label="End time:"), False, False, 0)
        end_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        end_spin.set_value(self.config.get("end_hour", 6))
        end_box.pack_start(end_spin, False, False, 0)
        end_box.pack_start(Gtk.Label(label=":00"), False, False, 0)
        box.pack_start(end_box, False, False, 0)

        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.config["mode"] = "scheduled"
            self.config["start_hour"] = int(start_spin.get_value())
            self.config["end_hour"] = int(end_spin.get_value())
            save_config(self.config)
            self.update_sync_mode_buttons()
            self.apply_sync_mode_change()

        dialog.destroy()

    def on_cancel(self, btn):
        """Cancel the current transfer"""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Cancel Transfer?"
        )
        dialog.format_secondary_text("Are you sure you want to stop the current transfer?")
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            # Show immediate visual feedback
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-pending")
            self.status_text.set_text("Stopping Transfer...")
            self.progress.set_fraction(0)
            self.progress.set_text("Stopping...")
            self.message_label.set_text("Please wait...")
            self.file_info.set_text("")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.cancel_btn.set_sensitive(False)

            # Force UI update
            while Gtk.events_pending():
                Gtk.main_iteration()

            # Kill the transfer script and rsync
            subprocess.run(["sudo", "pkill", "-9", "-f", "on-usb-insert.sh"], capture_output=True)
            subprocess.run(["sudo", "pkill", "-9", "-f", "rsync"], capture_output=True)

            # Update status files using sudo (files may be owned by root)
            subprocess.run(["sudo", "bash", "-c", f'echo "CANCELLED" > {STATUS_FILE}'], capture_output=True)
            progress_json = json.dumps({
                "status": "cancelled",
                "message": "Transfer cancelled by user",
                "percent": 0,
                "files_done": 0,
                "files_total": 0
            })
            subprocess.run(["sudo", "bash", "-c", f"echo '{progress_json}' > {PROGRESS_FILE}"], capture_output=True)

            # Remove lock file
            subprocess.run(["sudo", "rm", "-f", "/tmp/usb-transfer.lock"], capture_output=True)

            # Mark transfer as done BEFORE UI update to prevent update_transfer from overwriting
            self.transfer_done = True
            self.device_ref_dialog_shown = False
            self.decision_dialog_shown = False

            # Update UI to cancelled state
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-pending")
            self.status_text.set_text("Transfer Cancelled")
            self.progress.set_fraction(0)
            self.progress.set_text("Cancelled")
            self.message_label.set_text("Transfer was stopped by user")
            self.file_info.set_text("You can now eject the USB drive")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.set_eject_button_state(True)
            self.cancel_btn.hide()

    def on_settings(self, btn):
        dialog = Gtk.Dialog(title="Sync Settings", transient_for=self, modal=True)
        dialog.set_default_size(350, 250)
        box = dialog.get_content_area()
        box.set_spacing(15)
        box.set_margin_start(20)
        box.set_margin_end(20)
        box.set_margin_top(20)

        mode_label = Gtk.Label(label="Sync Mode:")
        mode_label.set_xalign(0)
        box.pack_start(mode_label, False, False, 0)

        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_24hr = Gtk.RadioButton.new_with_label(None, "24hr (Always On)")
        mode_scheduled = Gtk.RadioButton.new_with_label_from_widget(mode_24hr, "Scheduled")
        if self.config.get("mode") == "24hr":
            mode_24hr.set_active(True)
        else:
            mode_scheduled.set_active(True)
        mode_box.pack_start(mode_24hr, False, False, 0)
        mode_box.pack_start(mode_scheduled, False, False, 0)
        box.pack_start(mode_box, False, False, 0)

        schedule_frame = Gtk.Frame(label="Schedule (when not 24hr)")
        schedule_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        schedule_box.set_margin_start(10)
        schedule_box.set_margin_end(10)
        schedule_box.set_margin_top(10)
        schedule_box.set_margin_bottom(10)

        start_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        start_box.pack_start(Gtk.Label(label="Start:"), False, False, 0)
        start_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        start_spin.set_value(self.config.get("start_hour", 22))
        start_box.pack_start(start_spin, False, False, 0)
        start_box.pack_start(Gtk.Label(label=":00"), False, False, 0)
        schedule_box.pack_start(start_box, False, False, 0)

        end_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        end_box.pack_start(Gtk.Label(label="End:"), False, False, 0)
        end_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        end_spin.set_value(self.config.get("end_hour", 6))
        end_box.pack_start(end_spin, False, False, 0)
        end_box.pack_start(Gtk.Label(label=":00"), False, False, 0)
        schedule_box.pack_start(end_box, False, False, 0)

        schedule_frame.add(schedule_box)
        box.pack_start(schedule_frame, False, False, 0)

        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            self.config["mode"] = "24hr" if mode_24hr.get_active() else "scheduled"
            self.config["start_hour"] = int(start_spin.get_value())
            self.config["end_hour"] = int(end_spin.get_value())
            save_config(self.config)

        dialog.destroy()

    def show_decision_dialog(self, existing_count, total_count):
        # Flag is already set before GLib.idle_add to prevent duplicates

        dialog = Gtk.Dialog(title="Files Already Exist", transient_for=self, modal=True)
        dialog.set_default_size(400, 200)
        box = dialog.get_content_area()
        box.set_spacing(20)
        box.set_margin_start(30)
        box.set_margin_end(30)
        box.set_margin_top(30)
        box.set_margin_bottom(20)

        msg = Gtk.Label(label=f"{existing_count} of {total_count} files already exist on the HDD.")
        msg.get_style_context().add_class("warning-text")
        msg.set_line_wrap(True)
        msg.set_justify(Gtk.Justification.CENTER)
        box.pack_start(msg, False, False, 0)

        question = Gtk.Label(label="Would you like to skip or overwrite them?")
        question.get_style_context().add_class("info-text")
        box.pack_start(question, False, False, 0)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        btn_box.set_halign(Gtk.Align.CENTER)

        skip_btn = Gtk.Button(label="Skip Existing")
        skip_btn.get_style_context().add_class("big-button")
        skip_btn.get_style_context().add_class("btn-primary")
        skip_btn.connect("clicked", lambda b: dialog.response(1))
        btn_box.pack_start(skip_btn, False, False, 0)

        overwrite_btn = Gtk.Button(label="Overwrite All")
        overwrite_btn.get_style_context().add_class("big-button")
        overwrite_btn.get_style_context().add_class("btn-warning")
        overwrite_btn.connect("clicked", lambda b: dialog.response(2))
        btn_box.pack_start(overwrite_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 10)

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()

        decision = "skip" if response == 1 else "overwrite"
        try:
            with open(DECISION_FILE, 'w') as f:
                f.write(decision)
        except:
            pass

        # NOTE: Don't reset flag here - it stays True until status changes
        # This prevents dialog from showing again while script processes the decision

    def show_device_reference_dialog(self, file_count, total_size):
        """Show dialog to get device reference name from user"""
        # Flag is already set before GLib.idle_add to prevent duplicates

        dialog = Gtk.Dialog(title="Device Reference", transient_for=self, modal=True)
        dialog.set_default_size(450, 280)
        box = dialog.get_content_area()
        box.set_spacing(15)
        box.set_margin_start(30)
        box.set_margin_end(30)
        box.set_margin_top(25)
        box.set_margin_bottom(15)

        # Header
        header = Gtk.Label(label="Name this data source")
        header.get_style_context().add_class("section-title")
        box.pack_start(header, False, False, 0)

        # Info about the USB
        info = Gtk.Label(label=f"Found {file_count} files ({total_size})")
        info.get_style_context().add_class("info-text")
        box.pack_start(info, False, False, 5)

        # Instructions
        instr = Gtk.Label(label="Enter a reference name for this data:")
        instr.get_style_context().add_class("info-text")
        instr.set_xalign(0)
        box.pack_start(instr, False, False, 5)

        # Text entry for device reference
        entry = Gtk.Entry()
        entry.set_placeholder_text("e.g., Camera_1, Control_South, Site_A")
        entry.set_max_length(50)
        entry.grab_focus()
        box.pack_start(entry, False, False, 5)

        # Hint about Enter key
        enter_hint = Gtk.Label(label="Press Enter to save")
        enter_hint.get_style_context().add_class("info-text")
        box.pack_start(enter_hint, False, False, 2)

        # Examples
        examples = Gtk.Label(label="Examples: Camera_1, Control_South, Drone_Flight_1")
        examples.get_style_context().add_class("message-text")
        examples.set_line_wrap(True)
        box.pack_start(examples, False, False, 3)

        # Button box
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        btn_box.set_halign(Gtk.Align.CENTER)

        # Use Default button
        default_btn = Gtk.Button(label="Use Default")
        default_btn.get_style_context().add_class("big-button")
        default_btn.get_style_context().add_class("btn-grey")
        default_btn.connect("clicked", lambda b: dialog.response(2))
        btn_box.pack_start(default_btn, False, False, 0)

        # Confirm button
        confirm_btn = Gtk.Button(label="Confirm")
        confirm_btn.get_style_context().add_class("big-button")
        confirm_btn.get_style_context().add_class("btn-primary")
        confirm_btn.connect("clicked", lambda b: dialog.response(1))
        btn_box.pack_start(confirm_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 10)

        # Allow Enter key to confirm
        entry.connect("activate", lambda e: dialog.response(1))

        dialog.show_all()
        response = dialog.run()

        device_ref = ""
        if response == 1:  # Confirm
            device_ref = entry.get_text().strip()
        # response == 2 means use default (empty string)

        dialog.destroy()

        # Write the device reference (or empty for default)
        try:
            with open(DEVICE_REF_FILE, 'w') as f:
                f.write(device_ref)
        except:
            pass

        # NOTE: Don't reset flag here - it stays True until status changes
        # This prevents dialog from showing again while script processes the input

    def clear_style_classes(self):
        """Remove all status style classes"""
        for cls in ["status-active", "status-complete", "status-failed", "status-pending"]:
            self.status_text.get_style_context().remove_class(cls)

    def set_eject_button_state(self, enabled):
        """Enable/disable eject button with proper styling"""
        self.eject_btn.set_sensitive(enabled)
        if enabled:
            self.eject_btn.get_style_context().add_class("btn-primary")
        else:
            self.eject_btn.get_style_context().remove_class("btn-primary")

    def update_all(self):
        self.time_label.set_text(datetime.now().strftime("%H:%M"))
        self.update_transfer()
        self.update_sync()
        return True

    def update_transfer(self):
        status = ""
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE) as f:
                    status = f.read().strip()
            except:
                pass

        progress = {}
        if os.path.exists(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE) as f:
                    content = f.read()
                    # Try to fix common JSON issues before parsing
                    # Fix malformed file_types with extra braces
                    import re
                    content = re.sub(r'"file_types": \{[^}]*\}+', '"file_types": {}', content)
                    progress = json.loads(content)
            except json.JSONDecodeError as e:
                # If JSON is still malformed, try to extract key values manually
                try:
                    with open(PROGRESS_FILE) as f:
                        content = f.read()
                    # Extract percent
                    pct_match = re.search(r'"percent":\s*(\d+)', content)
                    msg_match = re.search(r'"message":\s*"([^"]*)"', content)
                    file_match = re.search(r'"current_file":\s*"([^"]*)"', content)
                    status_match = re.search(r'"status":\s*"([^"]*)"', content)
                    speed_match = re.search(r'"speed":\s*"([^"]*)"', content)

                    progress = {
                        "percent": int(pct_match.group(1)) if pct_match else 0,
                        "message": msg_match.group(1) if msg_match else "Transferring...",
                        "current_file": file_match.group(1) if file_match else "",
                        "status": status_match.group(1) if status_match else "transferring",
                        "speed": speed_match.group(1) if speed_match else "--"
                    }
                except:
                    pass
            except:
                pass

        # Get message from progress file
        message = progress.get("message", "")

        # Handle different states
        if status in ["DETECTING", "MOUNTING", "SCANNING", "CHECKING"]:
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-active")
            self.set_eject_button_state(False)
            self.cancel_btn.show()
            self.cancel_btn.set_sensitive(True)
            self.transfer_done = False

            # Pulse progress bar for indeterminate states
            self.progress.pulse()

            if status == "DETECTING":
                self.status_text.set_text("USB Drive Detected")
            elif status == "MOUNTING":
                self.status_text.set_text("Mounting USB Drive...")
            elif status == "SCANNING":
                self.status_text.set_text("Scanning Files...")
            elif status == "CHECKING":
                self.status_text.set_text("Checking for Duplicates...")
                # Show duplicate count if available
                existing = progress.get("existing_files", 0)
                if existing > 0:
                    total = progress.get("files_total", 0)
                    self.file_info.set_text(f"Found {existing} duplicates out of {total} files")

            self.message_label.set_text(message)

            # Show file count if available
            total = progress.get("files_total", 0)
            if total > 0 and status != "CHECKING":
                self.file_info.set_text(f"Found {total} files")
            elif status != "CHECKING":
                self.file_info.set_text("")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")

        elif status == "PENDING_NAME":
            # Show device reference dialog
            if not self.device_ref_dialog_shown:
                # Set flag BEFORE scheduling dialog to prevent duplicates
                self.device_ref_dialog_shown = True
                total = progress.get("files_total", 0)
                # Get total size from message or calculate
                size_text = message if message else f"{total} files"
                GLib.idle_add(self.show_device_reference_dialog, total, size_text)

            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-pending")
            self.status_text.set_text("Enter Device Reference")
            self.progress.set_fraction(0)
            self.progress.set_text("Waiting for input...")
            self.message_label.set_text("Name this data source")
            self.file_info.set_text(f"Found {progress.get('files_total', 0)} files")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.set_eject_button_state(False)
            self.cancel_btn.show()
            self.cancel_btn.set_sensitive(True)

        elif status == "PENDING_DECISION":
            if not self.decision_dialog_shown:
                # Set flag BEFORE scheduling dialog to prevent duplicates
                self.decision_dialog_shown = True
                existing = progress.get("existing_files", 0)
                total = progress.get("files_total", 0)
                GLib.idle_add(self.show_decision_dialog, existing, total)

            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-pending")
            self.status_text.set_text("Files Already Exist")
            self.progress.set_fraction(0)
            self.progress.set_text("Waiting for input...")
            self.message_label.set_text(message)
            self.set_eject_button_state(False)
            self.cancel_btn.show()
            self.cancel_btn.set_sensitive(True)

        elif status == "TRANSFERRING":
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-active")
            self.status_text.set_text("Copying Files...")
            self.set_eject_button_state(False)
            self.cancel_btn.show()
            self.cancel_btn.set_sensitive(True)
            self.transfer_done = False

            pct = progress.get("percent", 0)
            self.progress.set_fraction(pct / 100)
            self.progress.set_text(f"{pct}%")

            self.message_label.set_text(message)

            done = progress.get("files_done", 0)
            total = progress.get("files_total", 0)
            self.file_info.set_text(f"Files: {done} / {total}")

            types = progress.get("file_types", {})
            if types:
                t = [f"{k}: {v}" for k, v in list(types.items())[:3]]
                self.file_types.set_text(" | ".join(t))

            # Show current file being transferred
            current_file = progress.get("current_file", "")
            if current_file:
                self.current_file_label.set_text(f">> {current_file}")
            else:
                self.current_file_label.set_text("")

            speed = progress.get("speed", "")
            eta = progress.get("eta", "")
            if speed and speed != "--":
                self.speed_label.set_text(f"Speed: {speed}  ETA: {eta}")

        elif status == "COMPLETE":
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-complete")

            files = progress.get("files_done", progress.get("files_total", 0))
            self.status_text.set_text(f"Transfer Complete!")
            self.progress.set_fraction(1.0)
            self.progress.set_text("100%")
            self.message_label.set_text(f"{files} files copied successfully")
            self.set_eject_button_state(True)
            self.cancel_btn.hide()
            self.transfer_done = True
            self.file_info.set_text("Safe to remove USB drive")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")

        elif status == "ALL_DUPLICATES":
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-complete")

            total = progress.get("files_total", 0)
            self.status_text.set_text("All Files Already Backed Up")
            self.progress.set_fraction(1.0)
            self.progress.set_text("100%")
            self.message_label.set_text(f"All {total} files already exist on the HDD")
            self.file_info.set_text("No new files to transfer")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.set_eject_button_state(True)
            self.cancel_btn.hide()
            self.transfer_done = True

        elif status == "CANCELLED":
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-pending")

            self.status_text.set_text("Transfer Cancelled")
            self.progress.set_fraction(0)
            self.progress.set_text("Cancelled")
            self.message_label.set_text("Transfer was stopped by user")
            self.file_info.set_text("")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.set_eject_button_state(True)
            self.cancel_btn.hide()
            self.transfer_done = True

        elif status == "FAILED":
            self.clear_style_classes()
            self.status_text.get_style_context().add_class("status-failed")

            files = progress.get("files_done", 0)
            if files > 0:
                self.status_text.set_text(f"Completed with Warnings")
                self.message_label.set_text(f"{files} files copied")
            else:
                self.status_text.set_text("Transfer Failed")
                self.message_label.set_text(message or "Check logs for details")

            self.progress.set_fraction(0)
            self.progress.set_text("Error")
            self.file_info.set_text("")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.set_eject_button_state(True)
            self.cancel_btn.hide()
            self.transfer_done = True

        elif not self.transfer_done:
            self.clear_style_classes()
            self.status_text.set_text("Insert USB drive to start backup")
            self.progress.set_fraction(0)
            self.progress.set_text("0%")
            self.message_label.set_text("Waiting for USB...")
            self.file_info.set_text("")
            self.file_types.set_text("")
            self.current_file_label.set_text("")
            self.speed_label.set_text("")
            self.set_eject_button_state(False)
            self.cancel_btn.hide()

    def is_usb_transfer_active(self):
        """Check if USB transfer is currently in progress"""
        if os.path.exists("/tmp/usb-transfer.lock"):
            return True
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE) as f:
                    status = f.read().strip()
                    return status in ["DETECTING", "MOUNTING", "SCANNING", "CHECKING",
                                     "PENDING_NAME", "PENDING_DECISION", "TRANSFERRING"]
            except:
                pass
        return False

    def update_sync(self):
        now = datetime.now()
        mode = self.config.get("mode", "scheduled")

        # Load cached Google Drive info
        self.load_gdrive_info()

        # Update Google Drive account/storage info
        if self.gdrive_info:
            used = self.gdrive_info.get("used_bytes", 0)
            total = self.gdrive_info.get("total_bytes", 0)
            free = self.gdrive_info.get("free_bytes", 0)
            self.gdrive_account_label.set_text("Google Drive: Connected")
            self.gdrive_storage_label.set_text(
                f"Storage: {format_bytes(used)} / {format_bytes(total)} ({format_bytes(free)} free)"
            )
        else:
            self.gdrive_account_label.set_text("Google Drive: Connecting...")
            self.gdrive_storage_label.set_text("")

        # Check if USB transfer is in progress
        usb_active = self.is_usb_transfer_active()

        # Load sync status
        sync = {}
        if os.path.exists(SYNC_STATUS_FILE):
            try:
                with open(SYNC_STATUS_FILE) as f:
                    sync = json.load(f)
            except:
                pass

        folder = sync.get("folder", "RaPi-PEBL-Sync")
        self.sync_folder.set_text(f"Destination: gdrive:{folder}")

        # Remove previous mode styling
        self.sync_mode_label.get_style_context().remove_class("mode-24hr")
        self.sync_schedule.get_style_context().remove_class("sync-active")

        if mode == "24hr":
            self.sync_mode_label.set_text("24HR MODE - Always Syncing")
            self.sync_mode_label.get_style_context().add_class("mode-24hr")
            self.sync_schedule.set_text("Continuous sync enabled")
        elif mode == "night":
            self.sync_mode_label.set_text("Night Mode")
            start = 22  # 10pm
            end = 6     # 6am
            in_window = now.hour >= start or now.hour < end

            if in_window:
                self.sync_schedule.set_text("Sync active (10pm - 6am)")
                self.sync_schedule.get_style_context().add_class("sync-active")
            else:
                next_sync = now.replace(hour=start, minute=0)
                if now.hour >= end:
                    pass
                else:
                    next_sync += timedelta(days=1)
                delta = next_sync - now
                h = int(delta.total_seconds() // 3600)
                m = int((delta.total_seconds() % 3600) // 60)
                self.sync_schedule.set_text(f"Sync starts at 10pm (in {h}h {m}m)")
        else:  # scheduled/custom
            self.sync_mode_label.set_text("Custom Schedule")

            start = self.config.get("start_hour", 22)
            end = self.config.get("end_hour", 6)
            in_window = now.hour >= start or now.hour < end

            if in_window:
                self.sync_schedule.set_text(f"Sync active ({start}:00 - {end}:00)")
                self.sync_schedule.get_style_context().add_class("sync-active")
            else:
                next_sync = now.replace(hour=start, minute=0)
                if now.hour >= end:
                    pass
                else:
                    next_sync += timedelta(days=1)
                delta = next_sync - now
                h = int(delta.total_seconds() // 3600)
                m = int((delta.total_seconds() % 3600) // 60)
                self.sync_schedule.set_text(f"Next sync at {start}:00 (in {h}h {m}m)")

        # Update sync progress based on state
        # Remove sync-complete styling first (will be re-added if needed)
        self.sync_status_label.get_style_context().remove_class("sync-complete")

        if usb_active:
            # USB transfer in progress - show waiting message
            self.sync_status_label.set_text("Waiting for USB backup to complete...")
            self.sync_pct_progress.set_fraction(0)
            self.sync_pct_progress.set_text("Pending")
            self.sync_stats.set_text("New files will sync after backup")
        elif sync.get("active"):
            # Sync is actively running - show current session progress
            pct = sync.get("percent", 0)
            speed = sync.get("speed", "")
            synced = sync.get("files_synced", 0)
            remaining = sync.get("files_remaining", 0)
            total_this_session = synced + remaining if remaining > 0 else synced

            self.sync_status_label.set_text(f"Syncing: {synced} of {total_this_session} files")
            self.sync_pct_progress.set_fraction(pct / 100)
            self.sync_pct_progress.set_text(f"{pct}%")
            self.sync_stats.set_text(f"Uploading: {speed}")
        else:
            # Idle - check if fully synced or has pending files
            if self.gdrive_info:
                local_files = self.gdrive_info.get("local_files", 0)
                cloud_files = self.gdrive_info.get("cloud_files", 0)
                sync_pct = self.gdrive_info.get("sync_percent", 0)
                cloud_size = self.gdrive_info.get("cloud_size", 0)

                if sync_pct >= 100 and local_files > 0:
                    # Fully synced - show success message with green tick
                    self.sync_status_label.get_style_context().add_class("sync-complete")
                    self.sync_status_label.set_text(f"All files synced with Google Drive ({cloud_files}/{local_files})")
                    self.sync_pct_progress.set_fraction(1.0)
                    self.sync_pct_progress.set_text("100%")
                    self.sync_stats.set_text(f"Saved in gdrive:{folder}")
                elif local_files > cloud_files:
                    # Some files pending sync
                    pending = local_files - cloud_files
                    self.sync_status_label.set_text(f"{pending} files waiting to sync")
                    self.sync_pct_progress.set_fraction(sync_pct / 100)
                    self.sync_pct_progress.set_text(f"{sync_pct}% ({cloud_files}/{local_files})")
                    last = sync.get("last_sync", "Never")
                    self.sync_stats.set_text(f"Last sync: {last}")
                else:
                    # No files or unknown state
                    self.sync_status_label.set_text("Ready to sync")
                    self.sync_pct_progress.set_fraction(0)
                    self.sync_pct_progress.set_text("--")
                    self.sync_stats.set_text("")
            else:
                self.sync_status_label.set_text("Checking sync status...")
                self.sync_pct_progress.set_fraction(0)
                self.sync_pct_progress.set_text("--")
                self.sync_stats.set_text("")

    def on_eject(self, btn):
        # Unmount all USB drives
        subprocess.run(["bash", "-c",
            "for d in /media/pebl/*; do sudo umount \"$d\" 2>/dev/null; done"])
        subprocess.run(["sudo", "umount", "/media/usb-source"], capture_output=True)

        # Clear status files
        subprocess.run(["sudo", "rm", "-f", STATUS_FILE, PROGRESS_FILE, "/tmp/usb-transfer.lock"], capture_output=True)

        # Reset UI state
        self.transfer_done = False
        self.decision_dialog_shown = False
        self.device_ref_dialog_shown = False

        # Show "USB ejected" message briefly, then reset
        self.status_text.set_text("USB Ejected - Safe to Remove")
        self.message_label.set_text("Remove the USB drive, then insert a new one to backup")
        self.set_eject_button_state(False)

        # Schedule reset to waiting state after 3 seconds
        GLib.timeout_add(3000, self.reset_to_waiting)

    def on_remount(self, btn):
        """Remount USB devices - scan and mount any disconnected devices"""
        # Show feedback
        self.message_label.set_text("Scanning for USB devices...")

        # Force UI update
        while Gtk.events_pending():
            Gtk.main_iteration()

        mounted_devices = []
        errors = []

        # 1. Try to mount external HDD if not mounted
        result = subprocess.run(["mountpoint", "-q", "/media/external-hdd"])
        if result.returncode != 0:
            # Not mounted - try to mount
            mount_result = subprocess.run(
                ["sudo", "mount", "/dev/sda1", "/media/external-hdd"],
                capture_output=True, text=True
            )
            if mount_result.returncode == 0:
                mounted_devices.append("External HDD")
            else:
                # Try alternative device names
                for dev in ["/dev/sda1", "/dev/sdb1"]:
                    mount_result = subprocess.run(
                        ["sudo", "mount", dev, "/media/external-hdd"],
                        capture_output=True, text=True
                    )
                    if mount_result.returncode == 0:
                        mounted_devices.append(f"External HDD ({dev})")
                        break
                else:
                    errors.append("External HDD not found")
        else:
            mounted_devices.append("External HDD (already mounted)")

        # 2. Check for any USB drives that need mounting
        result = subprocess.run(
            ["bash", "-c", "lsblk -o NAME,FSTYPE,MOUNTPOINT -nr | grep -E 'vfat|ntfs|exfat' | grep -v sda"],
            capture_output=True, text=True
        )
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    dev_name = parts[0]
                    # If no mountpoint (3rd column missing or empty)
                    if len(parts) < 3 or not parts[2]:
                        # Try to mount via udisks
                        mount_result = subprocess.run(
                            ["udisksctl", "mount", "-b", f"/dev/{dev_name}"],
                            capture_output=True, text=True
                        )
                        if mount_result.returncode == 0:
                            mounted_devices.append(f"USB ({dev_name})")

        # Show results
        if mounted_devices:
            self.message_label.set_text(f"Mounted: {', '.join(mounted_devices)}")
            self.file_info.set_text("Devices ready")
        elif errors:
            self.message_label.set_text(f"Errors: {', '.join(errors)}")
            self.file_info.set_text("Check device connections")
        else:
            self.message_label.set_text("All devices already mounted")
            self.file_info.set_text("")

        # Refresh Google Drive info
        self.start_gdrive_info_fetch()

    def on_dismount_all(self, btn):
        """Safely dismount all USB devices for storage"""
        # Ask for confirmation
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Prepare for Storage?"
        )
        dialog.format_secondary_text(
            "This will safely unmount all USB devices and prepare the system for shutdown.\n\n"
            "Make sure all syncs are complete before proceeding."
        )
        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            # Show progress
            self.sync_status_label.set_text("Unmounting devices...")

            # Force UI update
            while Gtk.events_pending():
                Gtk.main_iteration()

            # Stop any running sync
            subprocess.run(["sudo", "pkill", "-f", "rclone"], capture_output=True)
            subprocess.run(["sudo", "pkill", "-f", "backup-to-gdrive"], capture_output=True)

            # Sync filesystem
            subprocess.run(["sync"], capture_output=True)

            # Unmount USB source
            subprocess.run(["bash", "-c",
                "for d in /media/pebl/*; do sudo umount \"$d\" 2>/dev/null; done"])
            subprocess.run(["sudo", "umount", "/media/usb-source"], capture_output=True)

            # Unmount external HDD
            subprocess.run(["sudo", "umount", "/media/external-hdd"], capture_output=True)

            # Show shutdown message
            shutdown_dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Safe to Disconnect"
            )
            shutdown_dialog.format_secondary_text(
                "All USB devices have been safely unmounted.\n\n"
                "You may now disconnect power from this device and store the backup system until further use."
            )
            shutdown_dialog.run()
            shutdown_dialog.destroy()

            # Update status
            self.sync_status_label.set_text("All devices unmounted - safe to power off")
            self.sync_stats.set_text("")

    def reset_to_waiting(self):
        """Reset UI to waiting for USB state"""
        self.clear_style_classes()
        self.status_text.set_text("Insert USB drive to start backup")
        self.progress.set_fraction(0)
        self.progress.set_text("0%")
        self.message_label.set_text("Waiting for USB...")
        self.file_info.set_text("")
        self.file_types.set_text("")
        self.current_file_label.set_text("")
        self.speed_label.set_text("")
        self.set_eject_button_state(False)
        self.cancel_btn.hide()
        self.transfer_done = False
        self.device_ref_dialog_shown = False
        self.decision_dialog_shown = False
        return False  # Don't repeat

    def check_usb_removed(self):
        """Check if USB was physically removed and reset UI"""
        # Only check when transfer is done (complete/failed/cancelled)
        if self.transfer_done:
            # Check if any USB storage is still connected
            result = subprocess.run(
                ["bash", "-c", "lsblk -d -o NAME,TRAN 2>/dev/null | grep usb | grep -v sda"],
                capture_output=True, text=True
            )
            # If no USB found (other than the HDD on sda), reset
            if not result.stdout.strip():
                # Clear status files
                subprocess.run(["sudo", "rm", "-f", STATUS_FILE, PROGRESS_FILE, "/tmp/usb-transfer.lock"], capture_output=True)
                self.reset_to_waiting()
        return True  # Keep checking

    def start_gdrive_info_fetch(self):
        """Start background thread to fetch Google Drive info"""
        thread = threading.Thread(target=fetch_gdrive_info, daemon=True)
        thread.start()
        # Refresh every 5 minutes
        GLib.timeout_add(300000, self.start_gdrive_info_fetch)
        return False

    def load_gdrive_info(self):
        """Load cached Google Drive info from file"""
        if os.path.exists(GDRIVE_INFO_FILE):
            try:
                with open(GDRIVE_INFO_FILE) as f:
                    self.gdrive_info = json.load(f)
            except:
                pass


if __name__ == "__main__":
    win = PEBLTransferMonitor()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
