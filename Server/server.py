import argparse
import base64
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


HOST = "0.0.0.0"
PORT = 8765
GROQ_MODEL = "qwen/qwen3.8-27b"
TAKE_SNAPSHOT_TIMEOUT_SECONDS = 90
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")


def load_env_file():
    """Load Server/.env without overriding variables supplied by the host."""
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip("\"'")
            if name:
                os.environ.setdefault(name, value)


load_env_file()


state_lock = threading.Lock()
app_state = {
    "status": "Waiting for client",
    "pending": [],
    "images": [],
}


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Snapshooter - Remote Screenshot Dashboard</title>
  <meta name="description" content="Snapshooter is a lightweight remote screenshot dashboard for requesting and receiving screenshots from a connected PC client.">
  <meta name="keywords" content="Snapshooter, remote screenshot dashboard, Python screenshot server, screenshot client">
  <meta name="author" content="Snapshooter">
  <meta name="robots" content="noindex, nofollow">
  <meta name="theme-color" content="#0f766e">
  <meta property="og:title" content="Snapshooter - Remote Screenshot Dashboard">
  <meta property="og:description" content="Request screenshots from a connected PC client and view them in a clean browser dashboard.">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary">
  <style>
    :root {
      --bg: #f5f7fb;
      --panel: #ffffff;
      --ink: #182230;
      --muted: #667085;
      --border: #d0d5dd;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --pending: #b54708;
      --done: #067647;
      --shadow: 0 10px 28px rgba(16, 24, 40, 0.08);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--ink);
      font-family: Segoe UI, Arial, sans-serif;
    }

    header {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 24px;
      border-bottom: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.94);
      backdrop-filter: blur(10px);
    }

    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 700;
    }

    .actions {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .status {
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }

    button {
      min-height: 40px;
      border: 0;
      border-radius: 6px;
      padding: 0 16px;
      background: var(--accent);
      color: white;
      font-size: 15px;
      font-weight: 650;
      cursor: pointer;
    }

    button:hover { background: var(--accent-dark); }
    button:disabled { opacity: 0.6; cursor: wait; }

    main {
      width: min(1180px, calc(100% - 32px));
      margin: 24px auto 40px;
    }

    .empty {
      padding: 28px;
      border: 1px dashed var(--border);
      border-radius: 8px;
      background: var(--panel);
      color: var(--muted);
      text-align: center;
    }

    .list {
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .shot {
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }

    .shot-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      color: var(--muted);
      font-size: 14px;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 0 10px;
      font-weight: 700;
      font-size: 12px;
      color: white;
      background: var(--done);
    }

    .badge.pending { background: var(--pending); }

    .shot img {
      display: block;
      width: 100%;
      height: auto;
      background: #101828;
    }

    .answer {
      margin-top: 16px;
      padding: 14px;
      border-radius: 6px;
      background: #f8fafc;
      white-space: pre-wrap;
      line-height: 1.55;
    }

    @media (max-width: 620px) {
      header {
        align-items: flex-start;
        flex-direction: column;
      }

      .actions {
        width: 100%;
        justify-content: space-between;
      }

      button { flex: 1; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Screenshot Server</h1>
    <div class="actions">
      <span class="status" id="status">Loading...</span>
      <button id="getImageButton" type="button">Get Image</button>
    </div>
  </header>

  <main>
    <div id="content" class="empty">No screenshots yet.</div>
  </main>

  <script>
    const button = document.getElementById("getImageButton");
    const statusEl = document.getElementById("status");
    const contentEl = document.getElementById("content");
    const authToken = new URLSearchParams(window.location.search).get("token")
      || window.sessionStorage.getItem("snapshooterToken")
      || "";

    if (authToken) {
      window.sessionStorage.setItem("snapshooterToken", authToken);
    }

    function authHeaders() {
      return authToken ? { "X-Screenshot-Token": authToken } : {};
    }

    function withToken(url) {
      if (!authToken) return url;
      const separator = url.includes("?") ? "&" : "?";
      return `${url}${separator}token=${encodeURIComponent(authToken)}`;
    }

    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      }[char]));
    }

    async function createRequest() {
      button.disabled = true;
      try {
        await fetch("/api/request", {
          method: "POST",
          cache: "no-store",
          headers: authHeaders(),
        });
        await refresh();
      } catch (error) {
        statusEl.textContent = "Request failed";
      } finally {
        button.disabled = false;
      }
    }

    function render(data) {
      const pendingCount = (data.pending || []).length;
      statusEl.textContent = pendingCount
        ? `${pendingCount} waiting for client`
        : (data.status || "Ready");

      const rows = [];

      for (const item of data.pending || []) {
        rows.push(`
          <article class="shot">
            <div class="shot-meta">
              <span>${escapeHtml(item.clicked_at)} · ${escapeHtml(item.request_id)}</span>
              <span class="badge pending">Waiting</span>
            </div>
          </article>
        `);
      }

      for (const item of data.images || []) {
        rows.push(`
          <article class="shot">
            <div class="shot-meta">
              <span>${escapeHtml(item.clicked_at)} · uploaded ${escapeHtml(item.uploaded_at)}</span>
              <span class="badge">${escapeHtml(item.client_id || "pc")}</span>
            </div>
            <img src="${escapeHtml(withToken(item.url))}" alt="Screenshot from ${escapeHtml(item.clicked_at)}">
            <div class="answer" role="status" aria-live="polite">${escapeHtml(item.answer || (item.analysis_status === "processing" ? "Analyzing questions…" : "Answer unavailable."))}</div>
          </article>
        `);
      }

      if (!rows.length) {
        contentEl.className = "empty";
        contentEl.textContent = "No screenshots yet.";
        return;
      }

      contentEl.className = "list";
      contentEl.innerHTML = rows.join("");
    }

    async function refresh() {
      try {
        const response = await fetch("/api/state", {
          cache: "no-store",
          headers: authHeaders(),
        });
        if (response.status === 401) {
          statusEl.textContent = "Add ?token=YOUR_TOKEN to the URL";
          return;
        }
        render(await response.json());
      } catch (error) {
        statusEl.textContent = "Disconnected";
      }
    }

    button.addEventListener("click", createRequest);
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""


TAKESNAP_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Snapshooter - Taking Screenshot</title>
  <style>
    body { margin: 0; padding: 28px; background: #f5f7fb; color: #182230; font-family: Segoe UI, Arial, sans-serif; }
    main { max-width: 680px; margin: 8vh auto; padding: 24px; border: 1px solid #d0d5dd; border-radius: 10px; background: white; }
    h1 { margin-top: 0; font-size: 24px; }
    #status { color: #475467; }
    .spinner { width: 28px; height: 28px; margin: 20px 0; border: 4px solid #d0d5dd; border-top-color: #0f766e; border-radius: 50%; animation: spin .8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    #result { padding: 14px; overflow-wrap: anywhere; border-radius: 6px; background: #f8fafc; white-space: pre-wrap; }
    #result:empty { display: none; }
    img { display: block; max-width: 100%; height: auto; margin-top: 18px; border-radius: 6px; }
  </style>
</head>
<body>
  <main>
    <h1>Snapshooter</h1>
    <div class="spinner" id="spinner" aria-hidden="true"></div>
    <p id="status" role="status" aria-live="polite">Sending screenshot request...</p>
    <pre id="result"></pre>
    <img id="screenshot" alt="Captured screenshot" hidden>
  </main>
  <script>
    const statusEl = document.getElementById("status");
    const resultEl = document.getElementById("result");
    const spinner = document.getElementById("spinner");
    const screenshot = document.getElementById("screenshot");
    const query = new URLSearchParams(location.search);
    const token = query.get("token") || sessionStorage.getItem("snapshooterToken") || "";
    if (token) sessionStorage.setItem("snapshooterToken", token);
    const headers = token ? { "X-Screenshot-Token": token } : {};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    function finish(payload, imageUrl) {
      spinner.hidden = true;
      statusEl.textContent = payload.success ? "Answer ready" : "Request failed";
      resultEl.textContent = JSON.stringify(payload, null, 2);
      if (imageUrl) {
        screenshot.src = token ? `${imageUrl}?token=${encodeURIComponent(token)}` : imageUrl;
        screenshot.hidden = false;
      }
    }

    async function run() {
      const start = Date.now();
      try {
        const createdResponse = await fetch("/api/request", { method: "POST", headers, cache: "no-store" });
        const created = await createdResponse.json();
        if (!createdResponse.ok) throw new Error(created.error || "Could not create screenshot request.");
        statusEl.textContent = "Waiting for the PC client to capture the screenshot...";

        while (Date.now() - start < 120000) {
          const stateResponse = await fetch("/api/state", { headers, cache: "no-store" });
          const state = await stateResponse.json();
          if (!stateResponse.ok) throw new Error(state.error || "Could not read screenshot status.");
          const image = (state.images || []).find((item) => item.request_id === created.request_id);
          if (image) {
            if (image.analysis_status === "complete" || image.analysis_status === "failed") {
              finish({
                success: image.analysis_status === "complete",
                request_id: image.request_id,
                answer: image.answer,
                screenshot_url: image.url,
                analysis_status: image.analysis_status,
              }, image.url);
              return;
            }
            statusEl.textContent = "Screenshot captured. Waiting for the answer...";
          }
          await sleep(700);
        }
        finish({ success: false, error: "Timed out waiting for screenshot capture and analysis." });
      } catch (error) {
        finish({ success: false, error: error.message || "Screenshot request failed." });
      }
    }

    run();
  </script>
</body>
</html>
"""


def now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def safe_filename(value):
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


def check_token(handler, parsed=None):
    expected = handler.server.shared_token
    if not expected:
        return True
    if handler.headers.get("X-Screenshot-Token", "") == expected:
        return True
    if parsed:
        query = parse_qs(parsed.query)
        return query.get("token", [""])[0] == expected
    return False


def send_json(handler, payload, status=200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def solve_image_questions(image_bytes, mime_type):
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Groq is not configured. Set GROQ_API_KEY in Server/.env or the server environment.")

    prompt = (
        "Read every question and option in the image, then solve each question. "
        "Return only the correct option and its answer text, one line per question, using exactly "
        "'Answer: Option [letter] - [option text]'. Do not repeat the question, list other options, "
        "or include explanations, confidence, introductions, or extra commentary. "
        "If the question is unreadable or cannot be answered from the image, say so briefly instead "
        "of guessing."
    )
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": GROQ_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime_type};base64,{encoded_image}",
                }},
            ],
        }],
        "temperature": 0.2,
        "max_completion_tokens": 2048,
    }
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Avoid urllib's generic Python-urllib signature, which Cloudflare may block.
            "User-Agent": "Snapshooter/1.0 (Groq API client)",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"Groq API error ({exc.code}): {detail}") from exc
    choices = result.get("choices", [])
    answer = choices[0].get("message", {}).get("content", "") if choices else ""
    if not answer:
        raise RuntimeError("Groq returned no answer for this image.")

    # Models sometimes append their original question and explanation despite
    # formatting instructions. Keep only lines that identify a chosen option.
    answer_lines = []
    answer_pattern = re.compile(
        r"^\s*(?:\d+[.)]\s*)?(?:\*{1,2})?Answer(?:\*{1,2})?:\s*"
        r"(?:\*{1,2})?Option\s+([A-H])(?:\*{1,2})?\s*[-:—–]\s*(.*?)\s*$",
        re.IGNORECASE,
    )
    for line in answer.splitlines():
        match = answer_pattern.match(line.strip().strip("*"))
        if match:
            option, answer_text = match.groups()
            answer_lines.append(f"Answer: Option {option.upper()} - {answer_text.strip().strip('*')}")
    if answer_lines:
        return "\n".join(answer_lines)
    return "Answer unavailable: Could not identify a correct option in the response."


def create_screenshot_request():
    request_id = uuid.uuid4().hex[:12]
    item = {
        "request_id": request_id,
        "clicked_at": now_text(),
        "client_id": None,
    }
    with state_lock:
        app_state["pending"].insert(0, item)
        app_state["status"] = "Request created"
    return item


def get_next_pending(client_id):
    with state_lock:
        if not app_state["pending"]:
            app_state["status"] = f"Client connected: {client_id}"
            return None
        item = app_state["pending"][-1]
        item["client_id"] = client_id
        app_state["status"] = f"Client working: {client_id}"
        return dict(item)


def complete_request(request_id, client_id, image_bytes):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    uploaded_at = now_text()

    with state_lock:
        match = None
        for item in app_state["pending"]:
            if item["request_id"] == request_id:
                match = item
                break

        if not match:
            return None

        app_state["pending"].remove(match)

    filename = safe_filename(f"{match['clicked_at']}_{request_id}.jpg")
    path = os.path.join(SCREENSHOT_DIR, filename)
    with open(path, "wb") as file:
        file.write(image_bytes)

    record = {
        "request_id": request_id,
        "clicked_at": match["clicked_at"],
        "uploaded_at": uploaded_at,
        "client_id": client_id or match.get("client_id") or "pc",
        "filename": filename,
        "url": f"/screenshots/{filename}",
        "analysis_status": "processing",
        "answer": "",
    }

    with state_lock:
        app_state["images"].insert(0, record)
        app_state["images"] = app_state["images"][:100]
        app_state["status"] = "Latest screenshot received"

    return record


def analyze_uploaded_screenshot(request_id, image_bytes):
    try:
        answer = solve_image_questions(image_bytes, "image/jpeg")
        status = "complete"
    except Exception as exc:
        answer = f"Answer unavailable: {exc}"
        status = "failed"

    with state_lock:
        for item in app_state["images"]:
            if item["request_id"] == request_id:
                item["answer"] = answer
                item["analysis_status"] = status
                break


class ServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/state":
            if not check_token(self, parsed):
                send_json(self, {"error": "Unauthorized"}, status=401)
                return
            with state_lock:
                payload = {
                    "status": app_state["status"],
                    "pending": list(app_state["pending"]),
                    "images": list(app_state["images"]),
                }
            send_json(self, payload)
            return

        if parsed.path.rstrip("/") == "/takesnap":
            if parse_qs(parsed.query).get("format", [""])[0] != "json":
                body = TAKESNAP_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if not check_token(self, parsed):
                send_json(self, {"success": False, "error": "Unauthorized"}, status=401)
                return

            request_item = create_screenshot_request()
            request_id = request_item["request_id"]
            deadline = time.monotonic() + TAKE_SNAPSHOT_TIMEOUT_SECONDS

            while time.monotonic() < deadline:
                with state_lock:
                    record = next(
                        (dict(item) for item in app_state["images"]
                         if item["request_id"] == request_id),
                        None,
                    )
                if record and record.get("analysis_status") in {"complete", "failed"}:
                    send_json(self, {
                        "success": record["analysis_status"] == "complete",
                        "request_id": request_id,
                        "answer": record.get("answer", ""),
                        "screenshot_url": record.get("url"),
                        "analysis_status": record["analysis_status"],
                    })
                    return
                time.sleep(0.2)

            with state_lock:
                app_state["pending"] = [
                    item for item in app_state["pending"]
                    if item["request_id"] != request_id
                ]
            send_json(self, {
                "success": False,
                "request_id": request_id,
                "error": "Timed out waiting for the screenshot and its analysis.",
                "timeout_seconds": TAKE_SNAPSHOT_TIMEOUT_SECONDS,
            }, status=504)
            return

        if parsed.path == "/healthz":
            send_json(self, {"status": "ok"})
            return

        if parsed.path == "/api/pending":
            if not check_token(self, parsed):
                send_json(self, {"error": "Unauthorized"}, status=401)
                return
            query = parse_qs(parsed.query)
            client_id = query.get("client_id", ["pc"])[0]
            pending = get_next_pending(client_id)
            send_json(self, pending or {})
            return

        if parsed.path.startswith("/screenshots/"):
            if not check_token(self, parsed):
                self.send_response(401)
                self.end_headers()
                return
            filename = os.path.basename(parsed.path)
            path = os.path.join(SCREENSHOT_DIR, filename)
            if not os.path.exists(path):
                self.send_response(404)
                self.end_headers()
                return
            with open(path, "rb") as file:
                body = file.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/request":
            if not check_token(self, parsed):
                send_json(self, {"error": "Unauthorized"}, status=401)
                return
            item = create_screenshot_request()
            send_json(self, item, status=201)
            return

        if parsed.path.startswith("/api/upload/"):
            if not check_token(self, parsed):
                send_json(self, {"error": "Unauthorized"}, status=401)
                return

            request_id = parsed.path.rsplit("/", 1)[-1]
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                send_json(self, {"error": "Empty upload"}, status=400)
                return

            image_bytes = self.rfile.read(length)
            client_id = self.headers.get("X-Client-Id", "pc")
            record = complete_request(request_id, client_id, image_bytes)
            if not record:
                send_json(self, {"error": "Unknown request"}, status=404)
                return

            threading.Thread(
                target=analyze_uploaded_screenshot,
                args=(request_id, image_bytes),
                daemon=True,
            ).start()
            send_json(self, record, status=201)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, _format, *args):
        return


def parse_args():
    parser = argparse.ArgumentParser(
        description="EC2 screenshot server dashboard."
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host/IP to bind.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional shared token required from client uploads and polling.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config()
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    host = args.host or config.get("host", HOST)
    port = args.port if args.port is not None else config.get("port", PORT)
    token = args.token if args.token is not None else config.get("token", "")

    server = ThreadingHTTPServer((host, port), ServerHandler)
    server.shared_token = token

    print(f"Server dashboard running at http://{host}:{port}")
    print("Open the EC2 public URL in your browser and click Get Image.")
    if args.token:
        print("Token protection is enabled.")
    else:
        print("Token protection is disabled. Use --token for public EC2 servers.")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
