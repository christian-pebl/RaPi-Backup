#!/usr/bin/env python3
"""
Simple web server to show USB transfer status
Access at http://<pi-ip>:8080
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
from datetime import datetime

STATUS_FILE = "/tmp/usb-transfer-status"
NOTIFICATIONS_FILE = "/var/log/usb-transfer/notifications.json"
LOG_FILE = "/var/log/usb-transfer/transfer.log"

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>USB Transfer Status</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="5">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 30px; color: #00d4ff; }
        .status-card {
            background: #16213e;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 20px;
            text-align: center;
        }
        .status {
            font-size: 2em;
            font-weight: bold;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }
        .status.idle { background: #2d3436; color: #b2bec3; }
        .status.transferring { background: #0984e3; color: white; animation: pulse 1.5s infinite; }
        .status.complete { background: #00b894; color: white; }
        .status.failed { background: #d63031; color: white; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        .notifications {
            background: #16213e;
            border-radius: 15px;
            padding: 20px;
        }
        .notification {
            padding: 15px;
            border-bottom: 1px solid #2d3436;
            display: flex;
            justify-content: space-between;
        }
        .notification:last-child { border-bottom: none; }
        .notification .time { color: #636e72; font-size: 0.9em; }
        .notification .title { color: #00d4ff; font-weight: bold; }
        .refresh-info {
            text-align: center;
            color: #636e72;
            margin-top: 20px;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>USB Transfer Monitor</h1>
        <div class="status-card">
            <h2>Current Status</h2>
            <div class="status {status_class}">{status}</div>
            <p>Last updated: {timestamp}</p>
        </div>
        <div class="notifications">
            <h2>Recent Activity</h2>
            {notifications}
        </div>
        <p class="refresh-info">Auto-refreshes every 5 seconds</p>
    </div>
</body>
</html>
"""

class StatusHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress access logs

    def do_GET(self):
        if self.path == '/api/status':
            self.send_json_response()
        else:
            self.send_html_response()

    def send_json_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        status = self.get_status()
        notifications = self.get_notifications()

        response = {
            "status": status,
            "timestamp": datetime.now().isoformat(),
            "notifications": notifications[-10:]
        }
        self.wfile.write(json.dumps(response).encode())

    def send_html_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

        status = self.get_status()
        status_class = status.lower().replace(' ', '')
        notifications = self.get_notifications()

        notif_html = ""
        for n in reversed(notifications[-10:]):
            notif_html += f'''
            <div class="notification">
                <div>
                    <span class="title">{n.get('title', 'Unknown')}</span>
                    <span> - {n.get('message', '')}</span>
                </div>
                <span class="time">{n.get('time', '')[:19]}</span>
            </div>
            '''

        if not notif_html:
            notif_html = '<div class="notification">No recent activity</div>'

        html = HTML_TEMPLATE.format(
            status=status,
            status_class=status_class,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            notifications=notif_html
        )
        self.wfile.write(html.encode())

    def get_status(self):
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, 'r') as f:
                    return f.read().strip() or "IDLE"
            except:
                return "IDLE"
        return "IDLE"

    def get_notifications(self):
        notifications = []
        if os.path.exists(NOTIFICATIONS_FILE):
            try:
                with open(NOTIFICATIONS_FILE, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                notifications.append(json.loads(line))
                            except:
                                pass
            except:
                pass
        return notifications

def run_server(port=8080):
    server = HTTPServer(('0.0.0.0', port), StatusHandler)
    print(f"Status server running at http://0.0.0.0:{port}")
    server.serve_forever()

if __name__ == '__main__':
    run_server()
