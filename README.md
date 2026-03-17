# BucketLens — cloud storage browser for developers

Browse your AWS S3, Azure Blob, and GCP Cloud Storage buckets with a thumbnail grid UI.
For engineers who already have cloud credentials configured and want a visual file browser.

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-AGPL%20v3-blue)

## Why

- Cloud storage consoles have no thumbnail view. Thousands of images means clicking one by one.
- Downloading everything locally to browse defeats the purpose of cloud storage.
- Existing tools require Docker, Electron, or cloud deployment. This is `pip install` and go.
- Your credentials never leave your machine. Flask proxies bytes on demand — nothing saved to disk.

## Features

### Browse & navigate
- Thumbnail grid with adjustable size slider
- Folder navigation with breadcrumb path
- Grid and list view toggle (`G`)
- Search/filter by filename (`/`)
- Sort by name, size, or date (list view)
- Group by date, size, or file type (grid view)

### Files & preview
- Lightbox viewer for images and video with arrow key navigation
- Video playback inline (mp4, mov, webm, avi, mkv)
- Text/code file preview modal (json, yaml, py, md, csv, html, sql, etc.)
- CSV rendered as tables
- File type icons and badges for non-media files
- Presigned URL sharing with expiry options (1h, 8h, 24h, 7d)
- Copy cloud URI to clipboard (`s3://`, `gs://`, Azure blob URL)

### Upload & delete
- Drag-and-drop or file picker upload to current path
- Bulk download selected files as ZIP (up to 500 files)
- 2-step delete: warning modal → type bucket name to confirm
- Every deletion logged to SQLite + plaintext audit log

### Security & audit
- Bound to `127.0.0.1` only — not reachable from the network
- No telemetry, no analytics, no external requests (except cloud APIs + Google Fonts)
- Credentials handled by each provider's default chain
- SQLite + plaintext audit log for all delete operations (`bucketlens_audit.db`, `bucketlens_audit.log`)

## Quick start

```bash
pip install flask boto3
python app.py
# → http://127.0.0.1:8080
```

On first launch, a provider selector asks you to choose AWS, Azure, or GCP.

## AWS setup

```bash
aws configure          # if not already done
python app.py          # uses ~/.aws/credentials
AWS_PROFILE=prod python app.py   # specific profile
```

Minimal IAM policy for production:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:ListAllMyBuckets", "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
    "Resource": ["arn:aws:s3:::your-bucket", "arn:aws:s3:::your-bucket/*"]
  }]
}
```

Full deployment guide (systemd, nginx, auth): [bucketlens.com/deploy.html](https://bucketlens.com/deploy.html)

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `BucketLens_PORT` | `8080` | Port to bind |
| `AWS_PROFILE` | `default` | AWS credentials profile |
| `AWS_DEFAULT_REGION` | from config | AWS region override |
| `AZURE_STORAGE_CONNECTION_STRING` | — | Azure connection string |
| `AZURE_STORAGE_ACCOUNT` | — | Azure account name (with `az login`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Path to GCP service account key |
| `GOOGLE_CLOUD_PROJECT` | — | GCP project ID |

## Provider support

| Provider | Status | Auth |
|---|---|---|
| AWS S3 | ✓ supported | `~/.aws/credentials` or env vars |
| Azure Blob | ✓ supported | Connection string or `az login` + account name |
| GCP Cloud Storage | ✓ supported | Service account key or `gcloud auth application-default login` |

Azure requires `pip install azure-storage-blob azure-identity`.
GCP requires `pip install google-cloud-storage`.

## Architecture

```
┌──────────┐   localhost:8080   ┌──────────┐    HTTPS     ┌─────────────┐
│  Browser  │ ◄────────────────►│  Flask   │ ◄───────────►│  AWS S3     │
│  (grid)   │  8KB chunks       │  (proxy) │  your creds  │  Azure Blob │
└──────────┘  nothing saved     └──────────┘              │  GCP Storage│
                                                          └─────────────┘
```

Flask proxies cloud storage bytes to `<img>` tags in 8KB chunks. Nothing saved to disk.

## Project structure

```
BucketLens/
├── app.py                  # Flask backend — StorageProvider pattern, all endpoints
├── audit.py                # SQLite + plaintext delete audit log
├── templates/
│   └── index.html          # HTML structure + inline modal styles
├── static/
│   ├── style.css           # Neon Cyber theme (CSS variables)
│   ├── app.js              # All frontend logic (vanilla JS)
│   └── logo.png            # Logo
├── website/                # Marketing site — bucketlens.com (S3 + CloudFront)
│   ├── index.html          # Landing page
│   ├── features.html       # Features page
│   ├── contact.html        # Contact / contributing
│   ├── deploy.html         # Self-hosting guide
│   ├── error.html          # 404 page
│   └── 403.html            # 403 page
├── requirements.txt
├── CHANGELOG.md
└── CLAUDE.md               # Development conventions
```

## Contributing

Issues, feature requests, and PRs: [bucketlens.com/contact.html](https://bucketlens.com/contact.html)

## License

AGPL-3.0 — free to use, modify, and share. If you modify BucketLens and run it as a network service, you must open source your version under the same license. See [LICENSE](LICENSE).
