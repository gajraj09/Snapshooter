# Snapshooter

Snapshooter is a lightweight Python remote screenshot dashboard. A hosted server shows a browser dashboard with a **Get Image** button, and a trusted PC client polls that server, captures the screen when requested, and uploads the screenshot back to the dashboard.

## Features

- Remote screenshot requests from a browser dashboard.
- Token-protected client polling and image uploads.
- Simple Python server with no runtime dependencies.
- Windows-friendly background client using `pythonw.exe` and the included VBS launcher.
- Render deployment blueprint included in `render.yaml`.
- SEO-aware HTML metadata for title, description, Open Graph, Twitter card, and mobile theme color. The dashboard is marked `noindex` because screenshots are private operational data.
- Groq-powered question answering for uploaded JPG, PNG, and WEBP images.

## Project Structure

```text
Snapshooter/
  Client/
    client_pc.py                 # Foreground screenshot client
    client_pc_background.pyw     # Background entrypoint
    Run Client Hidden.vbs        # Windows hidden launcher
    config.json                  # Client configuration file
    requirements.txt             # Client dependencies
  Server/
    server.py                    # Dashboard, API, upload receiver
    requirements.txt             # Server dependency note
  render.yaml                    # Render web service blueprint
```

## How It Works

1. Open the server dashboard in a browser.
2. Click **Get Image**.
3. The server creates a pending screenshot request.
4. The PC client polls `/api/pending` with `SNAPSHOOTER_TOKEN`.
5. When a request exists, the client captures the screen with `pyautogui`.
6. The client uploads the JPEG to `/api/upload/<request_id>`.
7. The dashboard refreshes and displays the latest screenshots.
8. After a screenshot arrives, the server automatically sends it to Groq for question analysis. The dashboard displays only the selected option and answer text below the screenshot.

### Request a screenshot and answer through the API

Call `GET /takesnap` to request a screenshot. The endpoint waits up to 90 seconds for capture and Groq analysis, then returns raw JSON text fields only (no HTML or image). The browser may show its normal loading indicator while the server waits. A successful response includes `success`, `status`, `request_id`, and `answer`; a failure includes `success`, `status`, `request_id`, and `error`. If token protection is enabled, pass the token as `?token=YOUR_TOKEN` or send the `X-Screenshot-Token` header.

```text
http://YOUR_SERVER_IP:8765/takesnap
```

## Configuration

Use the JSON config files instead of environment variables.

### Server config

Edit [Server/server.py](Server/server.py) or create a JSON config file if you want to override defaults. The server uses:

- `host`
- `port`
- `token`

### Client config

Edit [Client/config.json](Client/config.json) with your values:

```json
{
  "server_url": "server_deployed_url",
  "token": "change-this-token",
  "client_id": "my-pc",
  "poll_seconds": 1.0,
  "jpeg_quality": 85
}
```

## Run Locally

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Start the server:

```powershell
python Server\server.py --token change-this-token
```

Open:

```text
http://localhost:8765
```

Install and run the client on the PC whose screen should be captured:

```powershell
pip install -r Client\requirements.txt
python Client\client_pc.py --server-url http://localhost:8765 --token change-this-token --client-id my-pc
```

For background mode on Windows, update [Client/config.json](Client/config.json), then run:

```powershell
wscript "Client\Run Client Hidden.vbs"
```

## Deploy The Server On Render

For local use, paste your key into `Server/.env` on the `GROQ_API_KEY=` line. The server loads this file automatically and does not overwrite environment variables set by the host. `Server/.env` is ignored by Git. For deployment, set `GROQ_API_KEY` in the server's secret environment settings. Automatic screenshot analysis uses Groq's vision-capable `qwen/qwen3.8-27b` model via Groq's OpenAI-compatible Chat Completions API. See [Groq's vision guide](https://console.groq.com/docs/vision) for current model availability.

Render is the recommended target for this project because Snapshooter runs as a persistent Python web service.

1. Push this repository to GitHub.
2. In Render, choose **New** > **Blueprint**.
3. Connect the GitHub repository.
4. Render will read `render.yaml` and create a web service.
5. Set the shared token in the server and client config files.
6. After deployment, use the Render service URL as the client `server_url`.

Manual Render settings:

- Runtime: `Python`
- Build command: `python --version`
- Start command: `python Server/server.py`
- Health check path: `/healthz`

## GitHub Push Checklist

```powershell
git init
git add .
git commit -m "Prepare Snapshooter for deployment"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

Before pushing, make sure real secrets stay only in [Client/config.json](Client/config.json) or your deployment secrets store. Avoid committing screenshots, logs, or private config values.

## Security Notes

- Always set a strong token before deploying publicly.
- Do not commit screenshots, logs, or private config values.
- Render free instances have ephemeral storage, so uploaded screenshots can disappear after restarts. Use a persistent disk or object storage if you need long-term screenshot retention.
