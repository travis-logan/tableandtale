# Table & Tale

**Recipes worth remembering.**

Table & Tale is a self-hosted digital family cookbook. It is designed to preserve
family recipes, recipe-card photos, stories, contributors, comments, ratings,
shopping lists, meal pairings, and structured cooking instructions while remaining
easy to run on a Windows home server.

Current source version: **3.2.2**

## Stack

- **Backend:** Python 3 + Flask
- **Production WSGI server:** Waitress
- **Database:** SQLite
- **Frontend:** HTML, CSS, and vanilla JavaScript
- **PWA:** web app manifest + service worker
- **Image handling:** Pillow
- **Recipe-card OCR:** pytesseract / Tesseract OCR
- **Recipe import parsing:** BeautifulSoup + JSON-LD parsing
- **Windows deployment:** PowerShell + batch launchers
- **Remote access:** designed for HTTPS tunneling such as Tailscale Funnel

There is currently no React/Vue frontend, Node backend, ORM, Docker requirement,
or external cloud database.

## Development setup

### 1. Clone the repo

```bash
git clone <repo-url>
cd table-and-tale
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Create local config

```powershell
Copy-Item config.example.json config.json
```

Replace `secret_key` in `config.json` with a random value before using the app
with real accounts.

### 4. Run locally

```powershell
python app\app.py
```

Then open:

`http://localhost:3000`

## Important repository hygiene

Do **not** commit the live `C:\FamilyCookbook` directory wholesale.

The live install can contain:

- `config.json` with the Flask secret key
- `data/cookbook.db` with users and family data
- uploaded profile/recipe photos
- backups
- logs

Those paths are intentionally excluded in `.gitignore`.

For development, use a separate clone and a disposable development database.

## Source layout

```text
app/
  app.py                 Flask application, routes, schema and migrations
  static/
    index.html           Main client UI
    app.js               Client-side application logic
    styles.css           UI styles and themes
    sw.js                PWA service worker/cache behavior
    manifest.webmanifest PWA manifest
    *.svg                Branding/icons

data/
  seed_recipes.json      Initial recipe seed data

scripts/windows/
  run-server.ps1
  server-status.ps1
  SETUP-REMOTE-ACCESS.*
  uninstall-server.ps1

installer/windows/
  INSTALLER.ps1          Full Windows installer code from the v3.2.x line
  installer_helper.py    Installer DB/preflight helper
  UPDATE.ps1             v3.2.2 update script
  *.bat / LAUNCHER.ps1   Launchers

backup.py
requirements.txt
config.example.json
VERSION
```

## Current architectural notes

The project is intentionally simple and self-hosted, but it has grown quickly.
The backend is currently concentrated in one large Flask module and the frontend
uses compact vanilla JavaScript/CSS. A developer review should pay particular
attention to modularization, tests, security boundaries, migration strategy,
import parsing, and long-term maintainability.

See `docs/ARCHITECTURE.md` and `docs/DEVELOPER_REVIEW.md`.
