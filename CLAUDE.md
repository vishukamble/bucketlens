# CLAUDE.md

## Project Overview

BucketLens is a local cloud storage browser — a lightweight Flask app that gives users a Google Photos-like thumbnail grid view of their AWS S3, Azure Blob Storage, and GCP Cloud Storage buckets. Everything runs on the user's machine. No Docker, no cloud deployment.

## Tech Stack

- **Backend**: Python 3.8+, Flask, boto3 (required), azure-storage-blob + azure-identity (optional), google-cloud-storage (optional)
- **Frontend**: HTML structure in `templates/index.html`, CSS in `static/style.css`, JS in `static/app.js`. No framework, no build step
- **Fonts**: DM Sans + JetBrains Mono (Google Fonts CDN)
- **Theme**: Dark mode (Neon Cyber), CSS variables in `:root`

## Project Structure

```
BucketLens/
├── app.py                  # Flask backend (StorageProvider pattern, all API endpoints)
├── audit.py                # SQLite + plaintext delete audit log
├── templates/
│   └── index.html          # HTML structure + inline styles for help/cost/preview modals
├── static/
│   ├── style.css           # All base CSS (Neon Cyber theme, CSS variables in :root)
│   ├── app.js              # All JavaScript (state, events, rendering, API calls)
│   └── logo.png            # Logo (to be added)
├── website/                # Marketing site (bucketlens.com) — served by S3 + CloudFront
│   ├── index.html          # Landing page
│   ├── features.html       # Features page
│   ├── contact.html        # Contact page
│   ├── deploy.html         # Self-hosting guide
│   ├── error.html          # 404 error page
│   └── 403.html            # 403 error page
├── requirements.txt        # Python dependencies
├── CHANGELOG.md            # keepachangelog.com format
├── HANDOFF.md              # Project bible (partially stale)
├── README.md               # User-facing docs
└── CLAUDE.md               # This file
```

## File Disambiguation

| File | Purpose | Served by |
|------|---------|-----------|
| `templates/index.html` | App UI — cloud storage browser | Flask (app.py) |
| `website/index.html` | Marketing site — bucketlens.com | S3 + CloudFront |

Never modify these interchangeably. Always confirm which file is in scope before editing.

## Running Locally

```bash
pip install flask boto3
python app.py
# → http://127.0.0.1:8080
```

Requires cloud provider credentials configured:
- **AWS**: `~/.aws/credentials` via `aws configure`. Use `AWS_PROFILE=name` for non-default profiles.
- **Azure**: `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT` env var + `az login`
- **GCP**: `GOOGLE_APPLICATION_CREDENTIALS` env var or `gcloud auth application-default login`

Use `BucketLens_PORT=9090` for custom port.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serves frontend |
| GET | `/api/health?provider=X` | Check credentials for provider |
| GET | `/api/buckets?provider=X` | Lists all buckets/containers |
| GET | `/api/objects?bucket=X&prefix=Y&provider=Z` | Lists objects/folders at prefix |
| GET | `/api/object?bucket=X&key=Y&provider=Z&download=1` | Streams object bytes (proxy) |
| GET | `/api/presign?bucket=X&key=Y&expires=N&provider=Z` | Generates presigned/SAS URL |
| GET | `/api/preview?bucket=X&key=Y&provider=Z` | Returns text file content (max 1MB) |
| GET | `/api/audit?limit=N&bucket=X` | Returns recent delete events |
| POST | `/api/upload` | FormData with `bucket`, `prefix`, `provider`, `files[]` |
| POST | `/api/delete` | JSON body `{bucket, key, provider}` |
| POST | `/api/download-zip` | JSON body `{bucket, keys, provider}` → streamed ZIP |
| POST | `/api/reset-provider` | Clears provider cache (call when switching) |

All data endpoints return JSON. Errors return `{"error": "message"}` with appropriate HTTP status. The `provider` param defaults to `"aws"`.

## Architecture Decisions (Do Not Change)

- **Bind to `127.0.0.1` only** — never `0.0.0.0`. Security requirement
- **Proxy pattern** — Flask streams cloud storage bytes to browser via `/api/object`. Images render as `<img src="/api/object?...">`. Do not switch to presigned URLs for rendering
- **Separated static files** — CSS in `static/style.css`, JS in `static/app.js`, HTML structure in `templates/index.html`. No npm/bundler
- **No framework on frontend** — vanilla JS only. No React, no Vue, no jQuery
- **Default credential chains** — boto3 reads `~/.aws/credentials`, Azure uses `DefaultAzureCredential` or connection string, GCP uses `GOOGLE_APPLICATION_CREDENTIALS`
- **Minimal required dependencies** — only `flask` and `boto3` required. Azure and GCP deps are optional
- **StorageProvider abstraction** — all cloud operations go through `StorageProvider` base class with `S3Provider`, `AzureProvider`, `GCPProvider` implementations

## Code Conventions

### Python (app.py)
- `StorageProvider` base class with provider implementations (`S3Provider`, `AzureProvider`, `GCPProvider`)
- `get_provider(provider_type)` returns a cached provider instance from `_PROVIDERS` registry
- `_STORAGE_ERRORS` tuple catches all provider-specific exceptions in routes
- Return `jsonify()` for data, `Response(stream_with_context(...))` for binary streams
- Errors: `return jsonify({"error": str(exc)}), status_code`
- Handle `_STORAGE_ERRORS` (boto3 `ClientError`, Azure `AzureError`, GCP `GoogleCloudError`) in every endpoint

### JavaScript (static/app.js)
- Global state variables: `currentBucket`, `currentPrefix`, `currentObjects`, `currentFolders`, `browsableObjects`, `selectedKeys`, `currentView`, `lightboxIndex`, `currentProvider`, `sortField`, `sortDir`, `groupBy`, `searchQuery`
- DOM element refs cached as `$name` (e.g., `$bucket`, `$content`, `$lightbox`)
- Function naming: `verbNoun` (e.g., `loadObjects`, `renderGrid`, `toggleSelect`, `openLightbox`)
- Helper functions: `enc()` (encodeURIComponent), `esc()` (HTML escape), `formatSize()`, `showToast()`
- All API calls include `provider=${enc(currentProvider)}` parameter

### CSS (static/style.css)
- All colors/spacing via CSS variables in `:root`
- Component naming: `.component-name`, `.component-subpart` (e.g., `.card`, `.card-overlay`, `.card-checkbox`)
- `--thumb-size` is dynamically set by the size slider via JS
- Avoid `!important` — fix specificity in `style.css` instead of overriding in inline styles

## Key Implementation Details

- **Multi-cloud**: Provider selector modal on first visit, stored in `localStorage` as `bl_provider`. All API calls pass `provider` param
- **Folder navigation**: Uses delimiter-based listing (S3 `Delimiter="/"`, Azure `walk_blobs`, GCP `delimiter='/'`)
- **Streaming proxy**: `iter_chunks(8192)` for S3, chunked reads for GCP, `.chunks()` for Azure
- **Lazy loading**: All `<img>` tags use `loading="lazy"` browser attribute
- **Browsable types**: Images, video, text/code, PDF, archives. `media_type()` returns image/video/text/pdf/archive/other. `is_browsable()` = everything except 'other'
- **Lightbox navigation**: Arrow keys traverse media-only items (image + video) from `browsableObjects`
- **File preview**: Non-media browsable files open in preview modal (text rendered as code, CSV as table, 1MB limit)
- **Selection**: `selectedKeys` Set tracks selected items for bulk operations
- **Upload**: Drag-and-drop or file input → FormData POST with provider
- **Delete**: 2-step flow — warning modal → confirm view with bucket name input. Every deletion logged via `audit.py`
- **Download**: Selected files → POST to `/api/download-zip` → in-memory ZIP stream
- **Presigned URLs**: S3 native presigned, Azure SAS tokens (requires account key), GCP signed URLs v4
- **Cost awareness**: Bucket info modal, download >100MB warning, >200 image hint banner
- **Help drawer**: Slide-in panel with shortcuts, features, cost info, architecture diagram

## Roadmap Priority

1. Thumbnail caching
2. Virtual scrolling
3. Bulk download as streaming ZIP (currently in-memory)
4. EXIF metadata panel
5. PyPI package (`pip install BucketLens`)

## Testing

No test suite yet. Test manually against real cloud storage with mixed content (images, videos, non-media files, nested folders).
