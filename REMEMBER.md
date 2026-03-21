# REMEMBER.md
# Claude's internal reference. Read this at the start of every session.
# Keep this file updated as files are added, moved, or removed.
# This is NOT for users — write as much detail as needed for your own reference.

---

## CRITICAL FILE DISAMBIGUATION
There are TWO index.html files in this project. NEVER confuse them:
- `templates/index.html` → The Flask app UI. Served by Flask via render_template(). This is what users see at http://127.0.0.1:8080
- `website/index.html` → The marketing site. Served by S3/CloudFront at bucketlens.com. DO NOT edit this when working on app features.

---

## FILE MAP

### Backend (dev — run with `python app.py`)
- `app.py` — Flask core for dev mode. Shared helpers, `/` route, blueprint registration, `/api/audit`. No provider logic.
- `providers/__init__.py` — Empty package init.
- `providers/aws.py` — AWS S3 Blueprint. Routes: /api/buckets, /api/objects, /api/object, /api/upload, /api/delete. Uses `get_s3_client()` (cached boto3 client).
- `providers/azure.py` — Azure Blob Storage Blueprint. Routes: /api/azure/containers, /api/azure/objects, /api/azure/object. Uses `get_azure_client()` (cached BlobServiceClient via DefaultAzureCredential).
- `providers/gcp.py` — GCP stub Blueprint. Single route: /api/gcp/buckets → 501 not implemented.
- `audit.py` — SQLite + plaintext delete audit log.

### PyPI Package (installed — run with `bucketlens`)
- `pyproject.toml` — Package metadata, dependencies, entry point (`bucketlens = "bucketlens.cli:main"`).
- `MANIFEST.in` — Includes README, LICENSE, templates, static in sdist.
- `bucketlens/__init__.py` — Empty package init.
- `bucketlens/cli.py` — Entry point: imports app, opens browser after 1.2s delay, runs Flask.
- `bucketlens/app.py` — Package copy of app.py. Flask instantiated with explicit template_folder/static_folder pointing to `../templates` and `../static`. Imports use try/except for `bucketlens.X` then fallback to `X` (supports both installed and dev).
- `bucketlens/providers/__init__.py` — Empty package init.
- `bucketlens/providers/aws.py` — Package copy of providers/aws.py with fallback imports.
- `bucketlens/providers/azure.py` — Package copy of providers/azure.py with fallback imports.
- `bucketlens/providers/gcp.py` — Package copy of providers/gcp.py (no changes needed).

### App Frontend (the local tool)
- `templates/index.html` — Complete app UI. HTML + CSS + JS all in one file. No build step.
  - Currently: AWS only. No provider toggle yet.
  - Theme: Dark, CSS variables in :root. Accent: #4a6cf7. Fonts: DM Sans + JetBrains Mono.
  - Key JS globals: currentBucket, currentPrefix, currentObjects, browsableObjects, selectedKeys, currentView, lightboxIndex
  - Key JS functions: loadObjects(), renderGrid(), renderList(), toggleSelect(), openLightbox(), uploadFiles(), deleteSelected()

### Marketing Site (bucketlens.com)
- `website/index.html` — Homepage
- `website/features.html` — Features page
- `website/contact.html` — Contact page
- `website/deploy.html` — Deployment guide
- `website/error.html` — Error page
- `website/403.html` — 403 page
- All website files use same Neon Cyber design system (Electric Violet + Vibrant Emerald on near-black)

### Docs
- `CLAUDE.md` — Project overview, conventions, architecture decisions. Read this too.
- `HANDOFF.md` — Full project bible. Architecture, roadmap, known issues.
- `REMEMBER.md` — This file. Navigation reference for Claude.
- `README.md` — User-facing docs.

---

## CURRENT STATE (update this every session)

### Implemented Features
1. AWS S3 browser — bucket list, folder navigation, grid/list view, breadcrumb
2. Thumbnail grid with lazy loading, adjustable size slider
3. Lightbox viewer — images + video, arrow key nav, ESC to close
4. Upload — drag & drop + file input, progress toast
5. Bulk delete — checkbox selection, confirm dialog
6. View toggle — grid / list
7. Toast notifications — success/error
8. Skeleton loading state
9. Marketing website at bucketlens.com (website/ directory)
10. Azure Blob Storage backend (containers, objects, object streaming)
11. Provider-based blueprint architecture (providers/ directory)
12. Provider auto-detection via /api/providers; stored provider validated against backend on init
13. First-run config wizard (3-step: provider → configure → validate); config stored at ~/.bucketlens/config.json
14. "⚙ reconfigure" link in topbar — clears config, reloads page

### Security / Bug Fixes Applied (2026-03-20 audit session)
- C1: Azure streaming — replaced readall()/BytesIO with chunked stream_with_context (providers/azure.py)
- C2: Broken endpoints hidden — share button, EXIF "i" button, cache stats/clear, ZIP download button all hidden with display:none; JS functions preserved for re-enable later
- C3: Azure file preview — reads response as text (r.text()) instead of r.json() to avoid binary parse failure
- C4: XSS in onclick — replaced onclick="handleCardClick/toggleSelect(...)" with data-action/data-key + event delegation on $content
- C5: Content-Disposition injection — RFC 5987 encoding (filename*=UTF-8''...) in both aws.py and azure.py
- M5: Stale localStorage — initProvider() now fetches /api/providers first, validates stored provider against returned list before using it
- M7: Azure blueprint now only registers (and only added to REGISTERED_PROVIDERS) if AZURE_STORAGE_ACCOUNT env var is set

### Deferred Features (UI hidden, endpoints not yet implemented)
- Presigned URL / share link (/api/presign) — share buttons hidden in card grid and list view
- Bulk ZIP download (/api/download-zip) — download button hidden in topbar
- EXIF metadata panel (/api/exif) — "i" button hidden in lightbox and card grid
- Thumbnail cache stats (/api/cache/stats) — cache section hidden in help drawer
- Thumbnail cache clear (/api/cache/clear) — clear button hidden in help drawer

### In Progress
- GCP Cloud Storage implementation (currently stub only)

### In Progress (added this session)
- PyPI packaging — `bucketlens/` package created, `pyproject.toml` and `MANIFEST.in` in place. Dual-mode: `python app.py` (dev) and `pip install bucketlens && bucketlens` (installed).
- First-run config wizard — saves to `~/.bucketlens/config.json`; subsequent launches skip wizard and load directly.

### Config System
- Config file: `~/.bucketlens/config.json`
- Schema: `{"provider": "aws"|"azure"|"gcp", "azure_storage_account": "...", "gcp_project": "..."}`
- Endpoints: GET/POST/DELETE `/api/config`, GET `/api/validate`
- `before_request` hook in `bucketlens/app.py` reads config and sets `AZURE_STORAGE_ACCOUNT` env var at request time (not at startup)
- Azure blueprint always registers if azure SDK is installed (no env var gate)

### JS Initialization Architecture (templates/index.html)
- `app.js` loads normally (no defer) — inline `<script>` block runs AFTER app.js
- app.js IIFE calls `initProvider()` (async) — its fetch is still pending when inline script runs
- Inline script immediately hides `.topbar`, `.statusbar`, `#content`
- Patches `_pm.remove` to no-op and wraps `loadBuckets` behind a `_guardLifted` flag — neutralises the pending initProvider Promise's effects (modal removal + auto-load) before config is checked
- Saves `_originalInitProvider` and overrides `window.initProvider` to no-op — prevents any future re-calls
- `fetch('/api/config')` drives everything — single gate, no DOMContentLoaded needed (app.js globals available immediately)
- If configured: lift guard, remove modal via `_pmRemove`, show UI, call `_origLoadBuckets()`, validate silently
- If not configured: show wizard step 1, call real `/api/providers` (no interceptor) to update provider cards
- `wizardFinish()` lifts guard, removes modal, shows UI, calls `_origLoadBuckets()` — no reload needed
- `reconfigure()` DELETEs config and reloads

### Not Yet Started
- Thumbnail caching (Pillow)
- Virtual scrolling
- Publish to PyPI (run: `pip install build twine && python -m build && twine upload dist/*`)

---

## DEPENDENCIES
- Required: flask, boto3
- Optional (Azure): azure-storage-blob, azure-identity
- Optional (GCP, future): google-cloud-storage
- Optional (thumbnails, future): Pillow

## INFRA
- Hosted: S3 + CloudFront + Route53 → bucketlens.com
- Local dev: python app.py → http://127.0.0.1:8080
- Port override: BucketLens_PORT=9090
- AWS profile override: AWS_PROFILE=name
- Azure account: AZURE_STORAGE_ACCOUNT=bucketlens

---

## CONVENTIONS (never break these)
- Bind to 127.0.0.1 only, never 0.0.0.0
- No React, no Vue, no jQuery — vanilla JS only in templates/index.html
- No separate .css or .js files for the app — everything stays in templates/index.html
- No !important in CSS
- Python errors always return: jsonify({"error": str(exc)}), status_code
- Each provider is a Flask Blueprint in providers/ directory
- Shared helpers (is_browsable, media_type) live in app.py, imported by providers
