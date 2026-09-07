# Architecture

## Request flow

Browser / installed PWA
→ Flask application
→ SQLite database + local uploads
→ Waitress for the Windows production process

Remote access is intended to terminate HTTPS at a tunnel/proxy such as Tailscale
Funnel, with Flask/Waitress remaining on the local Windows host.

## Backend

`app/app.py` currently contains:

- startup/config loading
- SQLite schema creation
- additive schema migrations
- sessions/authentication
- CSRF and security headers
- user/admin/invite APIs
- user avatars/preferences
- recipe CRUD
- structured ingredients and cooking steps
- recipe revision snapshots
- ratings/comments/favorites/made-it history
- private notes
- shopping lists
- recipe pairings
- discovery/pantry matching
- file/photo uploads
- website recipe import
- ChatGPT shared-link import
- OCR/photo import
- public-sharing URL logic
- activity feed
- health endpoint
- SPA/static serving

## Database

SQLite is the source of truth for application/user data.

The existing production database should be treated as persistent state and should
never be replaced during an upgrade. Schema changes are expected to be additive,
versioned migrations with pre-upgrade backup/rollback.

## Frontend

The current UI is a single-page-style vanilla JavaScript application served by
Flask. PWA support is provided by `manifest.webmanifest` and `sw.js`.

The service worker is versioned and should not be allowed to hide new frontend
releases behind stale caches.

## Security model

Current controls include:

- Werkzeug password hashes
- server-side login/session checks
- invite-only registration
- Admin / Member / Guest role model
- CSRF tokens for state-changing API requests
- security headers
- basic login throttling
- authenticated recipe APIs
- HTTPS expected at the public tunnel/proxy
- no raw home-router port forwarding

A security review is recommended before any broader public deployment.

## Runtime private data

The following are runtime state, not source code:

- `config.json`
- `data/cookbook.db`
- SQLite WAL/SHM files
- `uploads/`
- `backups/`
- `logs/`

They must stay out of Git.
