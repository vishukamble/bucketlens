"""
BucketLens — A local cloud storage browser.
Browse your cloud storage buckets like Google Photos, entirely from your machine.

Usage (installed):
    pip install bucketlens
    bucketlens

Usage (dev):
    python app.py

Then open http://127.0.0.1:8080
"""

import json
import os
import pathlib
from flask import Flask, render_template, jsonify, request

try:
    from bucketlens import audit
except ImportError:
    import audit

_here = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = pathlib.Path.home() / ".bucketlens" / "config.json"


def _load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return None


app = Flask(
    __name__,
    template_folder=os.path.join(_here, "templates"),
    static_folder=os.path.join(_here, "static"),
)

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
# Inject env vars from config at request time (not at startup)
# ---------------------------------------------------------------------------

@app.before_request
def _inject_config_env():
    if not os.environ.get("AZURE_STORAGE_ACCOUNT"):
        cfg = _load_config()
        if cfg and cfg.get("provider") == "azure" and cfg.get("azure_storage_account"):
            os.environ["AZURE_STORAGE_ACCOUNT"] = cfg["azure_storage_account"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = _load_config()
    if cfg:
        return jsonify({"configured": True, **cfg})
    return jsonify({"configured": False})


@app.route("/api/config", methods=["POST"])
def save_config():
    data = request.get_json(force=True) or {}
    provider = data.get("provider")
    if provider not in ("aws", "azure", "gcp"):
        return jsonify({"error": "invalid provider"}), 400
    cfg = {"provider": provider}
    if provider == "azure" and data.get("azure_storage_account"):
        cfg["azure_storage_account"] = str(data["azure_storage_account"])
    if provider == "gcp" and data.get("gcp_project"):
        cfg["gcp_project"] = str(data["gcp_project"])
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    return jsonify({"ok": True})


@app.route("/api/config", methods=["DELETE"])
def delete_config():
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    return jsonify({"ok": True})


@app.route("/api/validate/auth")
def validate_auth():
    """Check only that credentials exist — does NOT require storage account."""
    provider = request.args.get("provider", "aws")
    if provider == "aws":
        try:
            import boto3
            boto3.client("s3").list_buckets()
            return jsonify({"authed": True})
        except Exception as exc:
            return jsonify({"authed": False, "error": str(exc)})
    elif provider == "azure":
        try:
            from azure.identity import DefaultAzureCredential
            DefaultAzureCredential().get_token("https://storage.azure.com/.default")
            return jsonify({"authed": True})
        except Exception:
            return jsonify({"authed": False, "error": "Not logged in. Run: az login"})
    return jsonify({"authed": False, "error": "Unknown provider"})


@app.route("/api/validate")
def validate_credentials():
    cfg = _load_config()
    if not cfg:
        return jsonify({"valid": False, "error": "Not configured"})
    provider = cfg.get("provider")
    if provider == "aws":
        try:
            import boto3
            boto3.client("s3").list_buckets()
            return jsonify({"valid": True})
        except Exception as exc:
            return jsonify({"valid": False, "error": str(exc)})
    elif provider == "azure":
        try:
            from azure.storage.blob import BlobServiceClient
            from azure.identity import DefaultAzureCredential
            account = cfg.get("azure_storage_account")
            if not account:
                return jsonify({"valid": False, "error": "No storage account configured"})
            client = BlobServiceClient(
                account_url=f"https://{account}.blob.core.windows.net",
                credential=DefaultAzureCredential(),
            )
            list(client.list_containers())
            return jsonify({"valid": True})
        except Exception as exc:
            return jsonify({"valid": False, "error": str(exc)})
    elif provider == "gcp":
        return jsonify({"valid": False, "error": "GCP not yet implemented"})
    return jsonify({"valid": False, "error": "Unknown provider"})


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
    try:
        from bucketlens.providers.aws import aws_bp
    except ImportError:
        from providers.aws import aws_bp
    app.register_blueprint(aws_bp)
    _aws_loaded = True
    REGISTERED_PROVIDERS.append("aws")
except ImportError:
    pass

_azure_loaded = False
try:
    try:
        from bucketlens.providers.azure import azure_bp
    except ImportError:
        from providers.azure import azure_bp
    app.register_blueprint(azure_bp)
    _azure_loaded = True
    REGISTERED_PROVIDERS.append("azure")
except ImportError:
    pass

_gcp_loaded = False
try:
    try:
        from bucketlens.providers.gcp import gcp_bp
    except ImportError:
        from providers.gcp import gcp_bp
    app.register_blueprint(gcp_bp)
    _gcp_loaded = True
except ImportError:
    pass


@app.route("/api/providers")
def list_providers():
    """Return which provider blueprints are currently active."""
    return jsonify({"providers": REGISTERED_PROVIDERS})
