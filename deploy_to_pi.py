#!/usr/bin/env python3
"""Deploy USB transfer scripts to Raspberry Pi"""

import paramiko
import os
import sys

PI_HOST = "192.168.1.159"
PI_USER = "pebl"
PI_PASSWORD = "pebl"
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")

FILES_TO_DEPLOY = {
    "on-usb-insert.sh": "/opt/usb-transfer/on-usb-insert.sh",
    "notify-user.sh": "/opt/usb-transfer/notify-user.sh",
    "backup-to-gdrive.sh": "/opt/usb-transfer/backup-to-gdrive.sh",
    "status-server.py": "/opt/usb-transfer/status-server.py",
    "transfer-gui.py": "/opt/usb-transfer/transfer-gui.py",
    "sync-config.json": "/opt/usb-transfer/sync-config.json",
}

SYSTEM_FILES = {
    "99-usb-transfer.rules": "/etc/udev/rules.d/99-usb-transfer.rules",
    "usb-transfer-status.service": "/etc/systemd/system/usb-transfer-status.service",
}

def deploy():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print(f"Connecting to {PI_HOST}...")
        client.connect(PI_HOST, username=PI_USER, password=PI_PASSWORD, timeout=10)
        sftp = client.open_sftp()

        # Deploy user scripts
        print("\nDeploying scripts to /opt/usb-transfer/...")
        for local_name, remote_path in FILES_TO_DEPLOY.items():
            local_path = os.path.join(SCRIPTS_DIR, local_name)
            if os.path.exists(local_path):
                print(f"  Uploading {local_name}...")
                sftp.put(local_path, remote_path)
            else:
                print(f"  WARNING: {local_name} not found")

        # Deploy system files to temp location first
        print("\nDeploying system files...")
        for local_name, remote_path in SYSTEM_FILES.items():
            local_path = os.path.join(SCRIPTS_DIR, local_name)
            if os.path.exists(local_path):
                temp_path = f"/tmp/{local_name}"
                print(f"  Uploading {local_name}...")
                sftp.put(local_path, temp_path)

        sftp.close()

        # Run setup commands
        print("\nSetting permissions and installing...")
        commands = [
            # Make scripts executable
            "chmod +x /opt/usb-transfer/*.sh",

            # Move system files with sudo
            "sudo mv /tmp/99-usb-transfer.rules /etc/udev/rules.d/",
            "sudo mv /tmp/usb-transfer-status.service /etc/systemd/system/",

            # Set correct ownership
            "sudo chown root:root /etc/udev/rules.d/99-usb-transfer.rules",
            "sudo chown root:root /etc/systemd/system/usb-transfer-status.service",

            # Reload udev rules
            "sudo udevadm control --reload-rules",
            "sudo udevadm trigger",

            # Enable and start status server
            "sudo systemctl daemon-reload",
            "sudo systemctl enable usb-transfer-status",
            "sudo systemctl start usb-transfer-status",
        ]

        stdin, stdout, stderr = client.exec_command(" && ".join(commands), timeout=60)
        exit_code = stdout.channel.recv_exit_status()

        if exit_code == 0:
            print("  Success!")
        else:
            print(f"  Warning: exit code {exit_code}")
            print(stderr.read().decode('utf-8', errors='replace'))

        # Verify deployment
        print("\nVerifying deployment...")
        stdin, stdout, stderr = client.exec_command("ls -la /opt/usb-transfer/")
        print(stdout.read().decode('utf-8', errors='replace'))

        print("\nChecking status service...")
        stdin, stdout, stderr = client.exec_command("sudo systemctl status usb-transfer-status --no-pager -l")
        print(stdout.read().decode('utf-8', errors='replace'))

        print(f"\nDone! Status dashboard available at: http://{PI_HOST}:8080")

    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        client.close()

    return True

if __name__ == "__main__":
    deploy()
