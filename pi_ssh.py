#!/usr/bin/env python3
"""SSH helper for Raspberry Pi automation"""

import paramiko
import sys
import os

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PI_HOST = "192.168.1.159"
PI_USER = "pebl"
PI_PASSWORD = "pebl"

def run_command(command, timeout=120):
    """Run a command on the Pi via SSH"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(PI_HOST, username=PI_USER, password=PI_PASSWORD, timeout=10)
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

        output = stdout.read().decode('utf-8', errors='replace')
        errors = stderr.read().decode('utf-8', errors='replace')
        exit_code = stdout.channel.recv_exit_status()

        if output:
            print(output)
        if errors:
            print(f"STDERR: {errors}", file=sys.stderr)

        return exit_code == 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False
    finally:
        client.close()

def copy_ssh_key():
    """Copy local SSH public key to Pi"""
    key_path = os.path.expanduser("~/.ssh/id_ed25519.pub")

    if not os.path.exists(key_path):
        print("No SSH key found at", key_path)
        return False

    with open(key_path, 'r') as f:
        public_key = f.read().strip()

    commands = [
        "mkdir -p ~/.ssh",
        f"echo '{public_key}' >> ~/.ssh/authorized_keys",
        "chmod 700 ~/.ssh",
        "chmod 600 ~/.ssh/authorized_keys",
        "sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys"  # Remove duplicates
    ]

    return run_command(" && ".join(commands))

def upload_file(local_path, remote_path):
    """Upload a file to the Pi via SFTP"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Resolve path
    local_path = os.path.abspath(local_path)

    if not os.path.exists(local_path):
        print(f"Error: Local file not found: {local_path}", file=sys.stderr)
        return False

    try:
        client.connect(PI_HOST, username=PI_USER, password=PI_PASSWORD, timeout=10)
        sftp = client.open_sftp()
        sftp.put(local_path, remote_path)
        sftp.close()
        print(f"Uploaded {local_path} to {remote_path}")
        return True
    except Exception as e:
        print(f"Error uploading file: {e}", file=sys.stderr)
        return False
    finally:
        client.close()

def write_remote_file(remote_path, content):
    """Write content directly to a remote file"""
    import base64
    encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
    cmd = f"echo '{encoded}' | base64 -d > '{remote_path}'"
    return run_command(cmd)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pi_ssh.py <command>")
        print("       python pi_ssh.py --copy-key")
        print("       python pi_ssh.py --upload <local> <remote>")
        sys.exit(1)

    if sys.argv[1] == "--copy-key":
        success = copy_ssh_key()
        sys.exit(0 if success else 1)
    elif sys.argv[1] == "--upload":
        if len(sys.argv) != 4:
            print("Usage: python pi_ssh.py --upload <local> <remote>")
            sys.exit(1)
        success = upload_file(sys.argv[2], sys.argv[3])
        sys.exit(0 if success else 1)
    else:
        command = " ".join(sys.argv[1:])
        success = run_command(command)
        sys.exit(0 if success else 1)
