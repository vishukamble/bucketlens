#!/usr/bin/env python3
"""
BucketLens — A local cloud storage browser.
Browse your cloud storage buckets like Google Photos, entirely from your machine.

Usage:
    pip install flask boto3
    python app.py

Then open http://127.0.0.1:8080
"""

import os
from flask import Flask, render_template, jsonify, request

import audit

app = Flask(__name__)

# ---------------------------------------------------------------------------
# File-type helpers (shared across all providers)
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff", ".tif", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}
PREVIEWABLE_EXTENSIONS = {
    '.txt', '.md', '.json', '.yaml', '.yml',
    '.xml', '.csv', '.html', '.htm', '.js',
    '.py', '.sh', '.env', '.log', '.sql',
    '.toml', '.ini', '.cfg', '.conf'
}
PDF_EXTENSIONS = {'.pdf'}
ARCHIVE_EXTENSIONS = {'.zip', '.tar', '.gz', '.tgz', '.rar', '.7z'}


def media_type(key: str) -> str:
    _, ext = os.path.splitext(key.lower())
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in PREVIEWABLE_EXTENSIONS:
        return "text"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    return "other"


def is_browsable(key: str) -> bool:
    return media_type(key) != "other"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/audit")
def get_audit_log():
    """Return recent delete events from the audit log."""
    try:
        limit = min(int(request.args.get("limit", 100)), 500)
    except ValueError:
        limit = 100
    bucket_filter = request.args.get("bucket")
    events = audit.get_recent_deletes(limit=limit, bucket=bucket_filter)
    return jsonify({"events": events, "total": len(events)})


# ---------------------------------------------------------------------------
# Blueprint registration — each provider loads only if its SDK is installed
# ---------------------------------------------------------------------------

REGISTERED_PROVIDERS = []

_aws_loaded = False
try:
    from providers.aws import aws_bp
    app.register_blueprint(aws_bp)
    _aws_loaded = True
    REGISTERED_PROVIDERS.append("aws")
except ImportError:
    pass

_azure_loaded = False
try:
    from providers.azure import azure_bp
    if os.environ.get("AZURE_STORAGE_ACCOUNT"):
        app.register_blueprint(azure_bp)
        _azure_loaded = True
        REGISTERED_PROVIDERS.append("azure")
except ImportError:
    pass

_gcp_loaded = False
try:
    from providers.gcp import gcp_bp
    app.register_blueprint(gcp_bp)
    _gcp_loaded = True
except ImportError:
    pass


@app.route("/api/providers")
def list_providers():
    """Return which provider blueprints are currently active."""
    return jsonify({"providers": REGISTERED_PROVIDERS})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("BucketLens_PORT", 8080))
    print(f"\n\u2601\ufe0f  BucketLens running at http://127.0.0.1:{port}\n")

    print("   \u2705  AWS S3 \u2014 ready (boto3 found)" if _aws_loaded
          else "   \u26a0\ufe0f   AWS S3 \u2014 skipped (pip install boto3)")
    print("   \u2705  Azure Blob Storage \u2014 ready (azure-storage-blob found)" if _azure_loaded
          else "   \u26a0\ufe0f   Azure Blob Storage \u2014 skipped (pip install azure-storage-blob azure-identity)")
    print("   \u2705  GCP Cloud Storage \u2014 stub loaded" if _gcp_loaded
          else "   \u26a0\ufe0f   GCP \u2014 skipped (pip install google-cloud-storage)")
    print()

    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=port, debug=False)
