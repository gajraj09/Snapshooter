import argparse
import io
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import pyautogui


DEFAULT_POLL_SECONDS = 1.0
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "client.log")


running = True


def handle_stop(_signum, _frame):
    global running
    running = False


def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    try:
        print(line)
    except Exception:
        pass

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as file:
            file.write(line + "\n")
    except Exception:
        pass


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def normalize_server_url(server_url):
    server_url = (server_url or "").strip()
    if server_url.startswith("http:") and not server_url.startswith("http://"):
        server_url = "http://" + server_url[len("http:"):]
    if server_url.startswith("https:") and not server_url.startswith("https://"):
        server_url = "https://" + server_url[len("https:"):]
    return server_url.rstrip("/")


def build_url(base_url, path):
    return base_url.rstrip("/") + path


def json_request(url, token=None, method="GET", payload=None, timeout=20):
    data = None
    headers = {"Accept": "application/json"}

    if token:
        headers["X-Screenshot-Token"] = token

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def upload_image(url, image_bytes, token=None, client_id="pc", timeout=60):
    headers = {
        "Content-Type": "image/jpeg",
        "Content-Length": str(len(image_bytes)),
        "X-Client-Id": client_id,
    }
    if token:
        headers["X-Screenshot-Token"] = token

    request = urllib.request.Request(
        url,
        data=image_bytes,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def capture_screen_jpeg(quality=85):
    screenshot = pyautogui.screenshot()
    buffer = io.BytesIO()
    screenshot.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def run_client(server_url, token, client_id, poll_seconds, jpeg_quality):
    server_url = normalize_server_url(server_url)
    log("Client started.")
    log(f"Server: {server_url}")
    log("Waiting for screenshot requests.")

    while running:
        try:
            query = urllib.parse.urlencode({"client_id": client_id})
            pending_url = build_url(server_url, f"/api/pending?{query}")
            pending = json_request(pending_url, token=token, timeout=15)

            request_id = pending.get("request_id")
            if not request_id:
                time.sleep(poll_seconds)
                continue

            log(f"Screenshot requested: {request_id}")
            image_bytes = capture_screen_jpeg(quality=jpeg_quality)
            upload_url = build_url(server_url, f"/api/upload/{request_id}")
            upload_image(
                upload_url,
                image_bytes,
                token=token,
                client_id=client_id,
                timeout=60,
            )
            log(f"Uploaded screenshot: {request_id}")

        except urllib.error.HTTPError as exc:
            log(f"HTTP error: {exc.code} {exc.reason}")
            time.sleep(max(2, poll_seconds))
        except urllib.error.URLError as exc:
            log(f"Connection error: {exc.reason}")
            time.sleep(max(2, poll_seconds))
        except Exception as exc:
            log(f"Client error: {exc}")
            time.sleep(max(2, poll_seconds))

    log("Client stopped.")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Background screenshot client for the EC2 server dashboard."
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="Server URL, for example http://YOUR_EC2_PUBLIC_IP:8765",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional shared token. Must match the server token if configured.",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Name shown to the server for this PC.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=None,
        help="How often to check EC2 for new requests.",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=None,
        help="JPEG quality from 1 to 95.",
    )
    return parser.parse_args()


def main():
    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    args = parse_args()
    config = load_config()

    server_url = args.server_url or config.get("server_url")
    if not server_url:
        log("Missing server URL. Add it to config.json or pass --server-url.")
        return 1

    token = args.token or config.get("token", "")
    client_id = args.client_id or config.get("client_id", "pc")
    poll_seconds = args.poll_seconds or config.get("poll_seconds", DEFAULT_POLL_SECONDS)
    jpeg_quality = args.jpeg_quality or config.get("jpeg_quality", 85)
    quality = max(1, min(int(jpeg_quality), 95))

    run_client(
        server_url=server_url,
        token=token,
        client_id=client_id,
        poll_seconds=max(0.2, float(poll_seconds)),
        jpeg_quality=quality,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
