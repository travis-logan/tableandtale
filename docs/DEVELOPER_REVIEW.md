# Developer Review Guide

This application was built rapidly and iteratively with AI assistance. It is real,
conventional source code, but it should be treated like an early product that now
needs an engineering hardening pass.

## Highest-value review areas

### 1. Security
Review:

- session cookie configuration
- CSRF implementation
- authorization on every mutating endpoint
- invite generation/expiry/reuse behavior
- login throttling and brute-force resistance
- uploaded file validation
- path traversal prevention
- SSRF protections in URL/ChatGPT recipe import
- HTML sanitization / XSS risk
- proxy trust / `ProxyFix` configuration
- public Tailscale Funnel exposure
- secret management

### 2. Database migrations and upgrade safety
The live family database must survive every release.

Review:

- schema migration idempotency
- transaction boundaries
- rollback behavior
- SQLite WAL handling
- backup verification
- preservation of user IDs/password hashes
- forward/backward compatibility

### 3. Modularization
`app/app.py` has grown into a large module.

Suggested eventual separation:

```text
app/
  __init__.py
  config.py
  db.py
  auth/
  recipes/
  shopping/
  imports/
  users/
  admin/
  uploads/
  migrations/
```

Frontend code could similarly be split into modules rather than one compact file.

### 4. Automated tests
Priority tests:

- setup/admin creation
- invite registration
- login/logout/password changes
- role/authorization boundaries
- recipe CRUD
- serving scaling
- scale-to-ingredient logic
- recipe revisions
- shopping-list scaling/deduplication
- imports
- schema migrations from historical DB versions
- upgrade preservation of existing users
- public invite URL selection
- service-worker update behavior

### 5. Recipe data model
Review whether ingredient quantities, units, step allocations, scalable flags,
serving counts, times, temperatures, pairings, and variants are normalized enough
for long-term use.

A future unit/conversion layer would improve scaling across tsp/Tbsp/cups/oz/g/etc.

### 6. Importers
Website, shared ChatGPT URL, text, and OCR imports should be considered untrusted
input. Review parsing accuracy and security separately.

### 7. Deployment
Consider whether the long-term developer workflow should use:

- a proper application factory
- environment-based configuration
- Alembic or another migration system
- pytest
- Ruff
- GitHub Actions
- Docker for development only, if useful

None of those are required just to keep the current Windows self-hosted model.
