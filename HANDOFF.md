# BucketLens — Project Bible & Handoff Document

> **Purpose**: Complete handoff for an AI assistant to continue development on BucketLens without asking the user to re-explain anything. Everything needed to understand, modify, and extend the project is here.

---

## 1. What Is BucketLens?

BucketLens is a **local, multi-cloud storage browser** that gives users a Google Photos-like thumbnail grid view of their AWS S3, Azure Blob Storage, and GCP Cloud Storage buckets. Runs entirely on the user's machine — no Docker, no cloud deployment.

### What's Built

- **Multi-cloud architecture** — `StorageProvider` abstraction with `S3Provider`, `AzureProvider`, `GCPProvider` implementations. Provider selector modal on first visit, stored in `localStorage`
- **Thumbnail grid + list view** — CSS grid with adjustable size slider, folder navigation with breadcrumbs, search/filter, sort (name/size/date), group by (date/size/type)
- **Lightbox** — full-screen image/video viewer with arrow key navigation across media-only items
- **File preview** — non-media browsable files (text, code, JSON, YAML, CSV, etc.) open in a preview modal. CSV rendered as tables. 1MB size limit
- **Upload** — drag-and-drop or file picker, FormData POST with provider
- **2-step delete** — warning modal showing file details → confirmation view requiring bucket name typed. Every deletion logged via `audit.py` to SQLite + plaintext
- **Bulk download** — selected files (up to 500) streamed as in-memory ZIP
- **Presigned URLs** — S3 native presigned, Azure SAS tokens (requires account key), GCP signed URLs v4. Expiry options: 1h, 8h, 24h, 7d
- **Copy cloud URI** — provider-aware: `s3://`, `gs://`, Azure blob URL
- **Cost awareness** — bucket info modal explaining proxy pattern + S3 costs, download >100MB warning, >200 image hint banner
- **Help drawer** — slide-in panel with keyboard shortcuts, features, cost info, architecture diagram
- **Audit logging** — SQLite (WAL mode) + plaintext file for all delete operations
- **Neon Cyber theme** — dark theme with Electric Violet + Vibrant Emerald, CSS variables in `:root`

### Core Design Principles

1. **Everything stays local** — bound to `127.0.0.1` only, images streamed on-demand (never saved to disk)
2. **Minimal dependencies** — `pip install flask boto3` and go. Azure/GCP deps optional
3. **Zero configuration** — reads existing cloud credentials via each provider's default chain
4. **Proxy pattern** — Flask streams cloud storage bytes to `<img>` tags via `/api/object`. No presigned URLs for rendering
5. **No framework on frontend** — vanilla JS only. No React, Vue, jQuery, npm, or bundler

---

## 2. Architecture

```
┌──────────┐   localhost:8080   ┌──────────┐    HTTPS     ┌─────────────┐
│  Browser  │ ◄────────────────►│  Flask   │ ◄───────────►│  AWS S3     │
│  (grid)   │  8KB chunks       │  (proxy) │  your creds  │  Azure Blob │
└──────────┘  nothing saved     └──────────┘              │  GCP Storage│
                                     │                    └─────────────┘
                                     │
                                ┌────┴────┐
                                │ audit.py│
                                │ SQLite  │
                                └─────────┘
```

### StorageProvider Abstraction

```
StorageProvider (base class)
├── list_buckets() -> list[str]
├── list_objects(bucket, prefix) -> {folders, objects, versioning_enabled}
├── get_object(bucket, key) -> (chunks_iterator, content_type, content_length)
├── put_object(bucket, key, data, content_type) -> None
├── delete_object(bucket, key) -> None
├── get_object_metadata(bucket, key) -> {size, last_modified, content_type}
├── generate_presigned_url(bucket, key, expires) -> str
└── check_permissions(bucket) -> {list, get, put, delete}

Implementations:
├── S3Provider(profile, region) — wraps boto3
├── AzureProvider() — wraps azure-storage-blob + azure-identity
└── GCPProvider() — wraps google-cloud-storage
```

Provider instances are cached in `_PROVIDERS` dict. `get_provider(provider_type)` is the factory. `/api/reset-provider` clears the cache when switching.

### Project Structure

```
BucketLens/
├── app.py                  # Flask backend — StorageProvider pattern, all endpoints (~820 lines)
├── audit.py                # SQLite + plaintext delete audit log (~94 lines)
├── templates/
│   └── index.html          # HTML structure + inline modal styles
├── static/
│   ├── style.css           # Neon Cyber theme (CSS variables in :root)
│   ├── app.js              # All frontend logic (vanilla JS, 14 state vars, 50+ functions)
│   └── logo.png            # Logo
├── website/                # Marketing site — bucketlens.com (S3 + CloudFront)
│   ├── index.html          # Landing page
│   ├── features.html       # Features page
│   ├── contact.html        # Contact / contributing
│   ├── deploy.html         # Self-hosting guide (systemd + nginx)
│   ├── error.html          # 404 page
│   └── 403.html            # 403 page
├── requirements.txt        # flask, boto3, azure-*, google-cloud-storage
├── CHANGELOG.md            # keepachangelog.com format
├── README.md               # User-facing docs
├── HANDOFF.md              # This file
└── CLAUDE.md               # Development conventions
```

### API Endpoints

| Method | Path | Params | Returns | Purpose |
|--------|------|--------|---------|---------|
| GET | `/` | — | HTML | Serves frontend |
| GET | `/api/health` | `provider` | `{ok, provider, error?}` | Credential check |
| GET | `/api/buckets` | `provider` | `{buckets[], provider}` | List all buckets/containers |
| GET | `/api/objects` | `bucket`, `prefix?`, `provider` | `{bucket, prefix, folders[], objects[]}` | List objects at prefix |
| GET | `/api/object` | `bucket`, `key`, `provider`, `download?` | Binary stream | Proxy cloud object bytes |
| GET | `/api/presign` | `bucket`, `key`, `expires?`, `provider` | `{url, expires_in, expires_at}` | Generate presigned/SAS URL |
| GET | `/api/preview` | `bucket`, `key`, `provider` | `{key, content, size, content_type}` | Text file preview (max 1MB) |
| GET | `/api/audit` | `limit?`, `bucket?` | `{events[], total}` | Recent delete events |
| POST | `/api/upload` | FormData: `bucket`, `prefix`, `provider`, `files[]` | `{uploaded[], errors[]}` | Upload files |
| POST | `/api/delete` | JSON: `{bucket, key, provider}` | `{deleted, timestamp}` | Delete object (audit logged) |
| POST | `/api/download-zip` | JSON: `{bucket, keys[], provider}` | ZIP stream | Bulk download as ZIP (max 500) |
| POST | `/api/reset-provider` | — | `{ok, message}` | Clear provider cache |

All endpoints accept `provider` param (`aws`, `azure`, `gcp`). Default: `aws`. Errors return `{"error": "message"}` with HTTP status. Routes catch `_STORAGE_ERRORS` tuple (dynamically built from available provider exception classes).

### audit.py Module

- SQLite database: `bucketlens_audit.db` (WAL mode, created at startup)
- Plaintext log: `bucketlens_audit.log` (append-only)
- Schema: `delete_log(id, timestamp, bucket, key, file_size, status, error_msg, provider, user_agent)`
- `log_delete()` — writes to both SQLite and plaintext. Failures silently caught (never breaks delete response)
- `get_recent_deletes(limit, bucket)` — returns list of dicts, max 500

---

## 3. Known Limitations & Technical Debt

### Performance
- **No thumbnail caching** — every page load re-fetches every visible image from cloud storage
- **No virtual scrolling** — 10,000+ items = 10,000+ DOM elements. `loading="lazy"` helps but DOM is heavy
- **ZIP download is in-memory** — `BytesIO` buffer, not true streaming. Large bulk downloads spike memory
- **Upload is non-chunked** — large files may timeout on slow connections

### Frontend
- **No EXIF metadata panel** — no image dimensions, GPS, camera info
- **No rename/move** — would need copy + delete pattern
- **No folder creation** — could be done with zero-byte key ending in `/`

### Security
- **No CSRF protection** — acceptable for localhost-only tool but worth noting
- **No auth** — anyone on the same machine can access localhost:8080

### Fixed Since v0.1.0
- ~~Full object read into memory~~ → streaming proxy with 8KB chunks
- ~~New boto3 session per request~~ → cached provider instances via `_PROVIDERS` registry
- ~~No presigned URLs~~ → implemented for all three providers
- ~~No search/filter~~ → search bar with `/` shortcut
- ~~No keyboard shortcuts beyond lightbox~~ → G, /, Ctrl+A, Ctrl+C, Ctrl+D, ?

---

## 4. Roadmap

### Completed [DONE]
- [DONE] Search/filter bar
- [DONE] Sort options (name, size, date)
- [DONE] Keyboard shortcuts (G, /, Ctrl+A, Ctrl+C, Ctrl+D, ?)
- [DONE] Streaming proxy (8KB chunks)
- [DONE] Singleton provider cache
- [DONE] Multi-cloud support (Azure Blob, GCP Cloud Storage)
- [DONE] Provider abstraction (`StorageProvider` base class)
- [DONE] Bulk download as ZIP
- [DONE] Copy cloud URI (provider-aware)
- [DONE] Presigned URL generation
- [DONE] 2-step delete with audit logging
- [DONE] File preview for text/code files

### Remaining (Priority Order)
1. **Thumbnail caching** — LRU cache keyed on `(bucket, key, last_modified)`, store resized thumbnails in temp dir
2. **Virtual scrolling** — IntersectionObserver to only render visible grid cells
3. **EXIF metadata panel** — side panel with image EXIF data (Pillow)
4. **PyPI packaging** — `pip install bucketlens`, CLI entry point
5. **Team mode + auth** — multi-user server deployment with authentication
6. **SSO** — SAML/OIDC integration for team deployments
7. **Rename/move objects** — copy + delete pattern
8. **Folder creation** — zero-byte key ending in `/`

---

## 5. How to Make Changes

### Adding a New Cloud Provider

1. Create a class inheriting from `StorageProvider` in `app.py`
2. Implement all 8 methods: `list_buckets`, `list_objects`, `get_object`, `put_object`, `delete_object`, `get_object_metadata`, `generate_presigned_url`, `check_permissions`
3. Add the provider's exception class to `_STORAGE_ERRORS` list (before it's converted to tuple)
4. Add a branch in `get_provider()` for the new provider type
5. Add provider option in the frontend selector modal (`templates/index.html`)
6. Add URI format in `copyS3URI()` in `static/app.js`

### Adding a New API Endpoint

1. Add route function in `app.py` following existing pattern
2. Use `get_provider(provider_type)` — never instantiate providers directly
3. Accept `provider` param from request args/body, default to `"aws"`
4. Return `jsonify()` for data, `Response(stream_with_context(...))` for binary
5. Catch `_STORAGE_ERRORS` (not just `ClientError`) for error handling
6. Return errors as `jsonify({"error": str(exc)}), status_code`

### Modifying the Frontend

Files are separated:
- **HTML structure**: `templates/index.html` (also contains inline styles for modals)
- **CSS**: `static/style.css` (all base styles, CSS variables in `:root`)
- **JS**: `static/app.js` (all logic, state management, API calls)

All API calls in `app.js` must include `provider=${enc(currentProvider)}` parameter. The `enc()` helper is `encodeURIComponent`.

### audit.py Pattern

All destructive operations should be logged. Currently only deletes are logged. To add a new audited action:
1. Add a new table or extend `delete_log` schema in `audit.py`
2. Call the logging function in the route, passing `provider` and `user_agent`
3. Wrap in try/except — audit failures must never break the main operation

### Provider Parameter Pattern

Every API call from frontend to backend passes `?provider=aws|azure|gcp`. The JS global `currentProvider` (stored in `localStorage` as `bl_provider`) determines which value is sent. When switching providers, `/api/reset-provider` is called to clear the backend cache.

---

## 6. Code Conventions

### Python (app.py)
- `StorageProvider` base class pattern — all cloud operations go through it
- `get_provider(provider_type)` factory with `_PROVIDERS` cache
- `_STORAGE_ERRORS` tuple for cross-provider error handling in all routes
- Return `jsonify()` for data, `Response(stream_with_context(...))` for streams
- Errors: `return jsonify({"error": str(exc)}), status_code`
- `datetime.now(timezone.utc)` — never `datetime.utcnow()`

### JavaScript (static/app.js)
- 14 global state variables: `currentBucket`, `currentPrefix`, `currentObjects`, `currentFolders`, `browsableObjects`, `selectedKeys`, `currentView`, `lightboxIndex`, `currentProvider`, `sortField`, `sortDir`, `groupBy`, `searchQuery`, `isDragging`
- DOM refs cached as `$name` (`$bucket`, `$content`, `$lightbox`, etc.)
- Function naming: `verbNoun` (`loadObjects`, `renderGrid`, `toggleSelect`, `openLightbox`)
- Helpers: `enc()` (encodeURIComponent), `esc()` (HTML escape), `formatSize()`, `showToast()`
- All fetch calls include `provider=${enc(currentProvider)}`

### CSS (static/style.css)
- All colors/spacing via CSS variables in `:root` (26 variables)
- Component naming: `.component-name`, `.component-subpart`
- `--thumb-size` dynamically set by JS slider
- No `!important` — ever. Fix specificity in style.css instead

### Two-Step Delete Pattern
1. User clicks delete → warning modal shows file details and cost info
2. User must type bucket name to confirm → actual deletion + audit log entry

### Cost Warning Pattern
- Bucket info modal on first bucket selection (dismissable, stored in `localStorage`)
- Download >100MB shows size warning
- >200 images shows a hint banner (MutationObserver watches DOM)

### Modal Patterns
Templates/index.html contains 11 modals including: provider selector, bucket info, delete warning, delete confirm, help drawer, file preview, presigned URL, lightbox, cost hint, upload progress, toast container.

---

## 7. Environment & Dependencies

| Dependency | Version | Required | Purpose |
|-----------|---------|----------|---------|
| Python | 3.8+ | Yes | Runtime |
| Flask | any | Yes | Web server |
| boto3 | any | Yes | AWS S3 SDK |
| azure-storage-blob | any | Optional | Azure Blob Storage SDK |
| azure-identity | any | Optional | Azure credential chain |
| google-cloud-storage | any | Optional | GCP Cloud Storage SDK |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BucketLens_PORT` | `8080` | Port to bind |
| `AWS_PROFILE` | `default` | AWS credentials profile |
| `AWS_DEFAULT_REGION` | from config | AWS region override |
| `AZURE_STORAGE_CONNECTION_STRING` | — | Azure connection string |
| `AZURE_STORAGE_ACCOUNT` | — | Azure account name (with `az login`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Path to GCP service account key |
| `GOOGLE_CLOUD_PROJECT` | — | GCP project ID |

### Runtime Files (gitignored)

- `bucketlens_audit.db` — SQLite audit database
- `bucketlens_audit.log` — plaintext audit log

---

## 8. File Disambiguation — CRITICAL

| File | Purpose | Served by |
|------|---------|-----------|
| `templates/index.html` | App UI — cloud storage browser | Flask (`app.py`) |
| `website/index.html` | Marketing site — landing page | S3 + CloudFront |
| `website/features.html` | Features page | S3 + CloudFront |
| `website/contact.html` | Contact / contributing page | S3 + CloudFront |
| `website/deploy.html` | Self-hosting deployment guide | S3 + CloudFront |
| `website/error.html` | 404 error page | CloudFront |
| `website/403.html` | 403 error page | CloudFront |

**NEVER edit these interchangeably.** `templates/index.html` is the application. `website/*.html` is the marketing site at bucketlens.com. Always confirm which file is in scope before editing.

---

## 9. Deployment

### Local single-user (default)
```bash
pip install flask boto3
python app.py
# → http://127.0.0.1:8080
```

### Team server
- systemd service + nginx reverse proxy
- Full guide: `website/deploy.html` (also live at bucketlens.com/deploy.html)
- Requires auth layer (nginx basic auth or SSO) since BucketLens has no built-in auth

### Marketing site (bucketlens.com)
- Static files in `website/` directory
- Hosted on S3 + CloudFront + Route 53
- Deploy command:
```bash
aws s3 sync website/ s3://bucketlens.com --delete
aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"
```
