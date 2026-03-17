#!/usr/bin/env python3
"""
BucketLens — A local cloud storage browser.
Browse your S3 buckets like Google Photos, entirely from your machine.

Usage:
    pip install flask boto3
    python app.py

Then open http://127.0.0.1:8080
"""

import os
import hashlib
import mimetypes
import tempfile
import zipfile
import io as _io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, jsonify, request, render_template, abort, Response, stream_with_context, make_response
import audit

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError
except ImportError:
    print("\n❌  boto3 is required. Install it with:\n    pip install boto3\n")
    raise SystemExit(1)

try:
    from google.cloud import storage as gcs
    from google.cloud.exceptions import GoogleCloudError
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False

try:
    from azure.storage.blob import (
        BlobServiceClient,
        generate_blob_sas,
        BlobSasPermissions,
        ContentSettings,
    )
    from azure.identity import DefaultAzureCredential
    from azure.core.exceptions import AzureError
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

try:
    from PIL import Image as PILImage
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Thumbnail cache setup
# ---------------------------------------------------------------------------
CACHE_DIR = Path(tempfile.gettempdir()) / "bucketlens_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
THUMB_SIZE = (400, 400)
CACHE_MAX_BYTES = 500 * 1024 * 1024  # 500MB

# ---------------------------------------------------------------------------
# Build a tuple of all storage-provider exceptions for route error handling
# ---------------------------------------------------------------------------
_STORAGE_ERRORS = [ClientError]
if AZURE_AVAILABLE:
    _STORAGE_ERRORS.append(AzureError)
if GCP_AVAILABLE:
    _STORAGE_ERRORS.append(GoogleCloudError)
_STORAGE_ERRORS = tuple(_STORAGE_ERRORS)

# ---------------------------------------------------------------------------
# Thumbnail cache helpers
# ---------------------------------------------------------------------------


def get_cache_key(provider: str, bucket: str, key: str, etag: str = '') -> str:
    """Filesystem-safe cache filename. Invalidates when object changes."""
    raw = f"{provider}:{bucket}:{key}:{etag}"
    hash_ = hashlib.sha256(raw.encode()).hexdigest()[:16]
    ext = Path(key).suffix.lower() or '.bin'
    return f"{hash_}{ext}"


def get_cached_thumb(cache_key: str):
    """Returns (bytes, content_type) if cache hit, else (None, None)."""
    path = CACHE_DIR / cache_key
    if path.exists():
        try:
            data = path.read_bytes()
            content_type = mimetypes.guess_type(cache_key)[0] or 'image/jpeg'
            return data, content_type
        except OSError:
            return None, None
    return None, None


def save_thumb_cache(cache_key: str, data: bytes) -> None:
    """Save thumbnail to cache. Evicts oldest files if over limit."""
    try:
        cache_files = sorted(CACHE_DIR.iterdir(), key=lambda p: p.stat().st_atime)
        total = sum(p.stat().st_size for p in cache_files)
        while total + len(data) > CACHE_MAX_BYTES and cache_files:
            oldest = cache_files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
        (CACHE_DIR / cache_key).write_bytes(data)
    except Exception:
        pass


def make_thumbnail(data: bytes, content_type: str):
    """Resize image to THUMB_SIZE using Pillow. Returns JPEG bytes or None."""
    if not PILLOW_AVAILABLE:
        return None
    try:
        img = PILImage.open(_io.BytesIO(data))
        img.thumbnail(THUMB_SIZE, PILImage.LANCZOS)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = PILImage.new('RGB', img.size, (0, 0, 0))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        buf = _io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def _fmt_size(b: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.2f} TB"


# ---------------------------------------------------------------------------
# File-type helpers (provider-agnostic)
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
# StorageProvider base class
# ---------------------------------------------------------------------------

class StorageProvider:
    def list_buckets(self) -> list:
        raise NotImplementedError

    def list_objects(self, bucket: str, prefix: str = '') -> dict:
        """
        Returns:
        {
          'folders': [str],
          'objects': [{
            'key': str,
            'size': int,
            'last_modified': str (ISO),
            'browsable': bool,
            'media_type': str
          }],
          'versioning_enabled': bool
        }
        """
        raise NotImplementedError

    def get_object(self, bucket: str, key: str) -> tuple:
        """Returns (bytes_iterator, content_type, content_length)"""
        raise NotImplementedError

    def put_object(self, bucket: str, key: str,
                   data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def delete_object(self, bucket: str, key: str) -> None:
        raise NotImplementedError

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        """Returns dict with size, last_modified, content_type"""
        raise NotImplementedError

    def generate_presigned_url(self, bucket: str,
                                key: str, expires: int) -> str:
        raise NotImplementedError

    def check_permissions(self, bucket: str) -> dict:
        """Returns {'list': bool, 'get': bool, 'put': bool, 'delete': bool}"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# S3Provider — wraps boto3
# ---------------------------------------------------------------------------

class S3Provider(StorageProvider):
    def __init__(self, profile: str = None, region: str = None):
        try:
            session = boto3.Session(
                profile_name=profile,
                region_name=region,
            )
            self._client = session.client('s3')
        except (NoCredentialsError, BotoCoreError) as exc:
            abort(500, description=f"AWS credential error: {exc}")

    def list_buckets(self) -> list:
        resp = self._client.list_buckets()
        return sorted(b["Name"] for b in resp.get("Buckets", []))

    def list_objects(self, bucket: str, prefix: str = '') -> dict:
        objects = []
        folders = set()

        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/")

        for page in pages:
            for cp in page.get("CommonPrefixes", []):
                folders.add(cp["Prefix"])
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                objects.append({
                    "key": key,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                    "browsable": is_browsable(key),
                    "media_type": media_type(key),
                })

        return {
            "folders": sorted(folders),
            "objects": objects,
            "versioning_enabled": False,
        }

    def get_object(self, bucket: str, key: str) -> tuple:
        resp = self._client.get_object(Bucket=bucket, Key=key)
        content_type = (
            resp.get("ContentType")
            or mimetypes.guess_type(key)[0]
            or "application/octet-stream"
        )
        content_length = resp.get("ContentLength", "")

        def generate():
            for chunk in resp["Body"].iter_chunks(chunk_size=8192):
                yield chunk

        return generate(), content_type, content_length

    def put_object(self, bucket: str, key: str,
                   data: bytes, content_type: str) -> None:
        self._client.put_object(
            Bucket=bucket, Key=key, Body=data, ContentType=content_type
        )

    def delete_object(self, bucket: str, key: str) -> None:
        self._client.delete_object(Bucket=bucket, Key=key)

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        head = self._client.head_object(Bucket=bucket, Key=key)
        return {
            "size": head.get("ContentLength", 0),
            "last_modified": head.get("LastModified", "").isoformat()
                             if head.get("LastModified") else "",
            "content_type": head.get("ContentType", ""),
        }

    def generate_presigned_url(self, bucket: str,
                                key: str, expires: int) -> str:
        return self._client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expires,
        )

    def check_permissions(self, bucket: str) -> dict:
        perms = {'list': False, 'get': False, 'put': False, 'delete': False}
        try:
            self._client.list_objects_v2(Bucket=bucket, MaxKeys=1)
            perms['list'] = True
        except ClientError:
            pass
        return perms


# ---------------------------------------------------------------------------
# GCPProvider — wraps google-cloud-storage
# ---------------------------------------------------------------------------

class GCPProvider(StorageProvider):
    def __init__(self):
        if not GCP_AVAILABLE:
            raise RuntimeError(
                "google-cloud-storage not installed. "
                "Run: pip install google-cloud-storage"
            )
        # Uses GOOGLE_APPLICATION_CREDENTIALS env var
        # or gcloud auth application-default login
        project = os.environ.get('GOOGLE_CLOUD_PROJECT')
        self._client = gcs.Client(project=project)

    def list_buckets(self) -> list:
        return sorted(b.name for b in self._client.list_buckets())

    def list_objects(self, bucket: str, prefix: str = '') -> dict:
        folders = set()
        objects = []

        blobs = self._client.list_blobs(bucket, prefix=prefix, delimiter='/')

        for blob in blobs:
            if blob.name.endswith('/'):
                continue
            objects.append({
                'key': blob.name,
                'size': blob.size,
                'last_modified': blob.updated.isoformat(),
                'browsable': is_browsable(blob.name),
                'media_type': media_type(blob.name),
            })

        for p in blobs.prefixes:
            folders.add(p)

        return {
            'folders': sorted(folders),
            'objects': objects,
            'versioning_enabled': False,
        }

    def get_object(self, bucket: str, key: str) -> tuple:
        blob = self._client.bucket(bucket).blob(key)
        blob.reload()
        content_type = (
            blob.content_type
            or mimetypes.guess_type(key)[0]
            or 'application/octet-stream'
        )

        def chunk_generator():
            with blob.open('rb') as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk

        return chunk_generator(), content_type, blob.size

    def put_object(self, bucket: str, key: str,
                   data: bytes, content_type: str) -> None:
        blob = self._client.bucket(bucket).blob(key)
        blob.upload_from_string(data, content_type=content_type)

    def delete_object(self, bucket: str, key: str) -> None:
        self._client.bucket(bucket).blob(key).delete()

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        blob = self._client.bucket(bucket).blob(key)
        blob.reload()
        return {
            'size': blob.size,
            'last_modified': blob.updated.isoformat(),
            'content_type': blob.content_type,
        }

    def generate_presigned_url(self, bucket: str,
                                key: str, expires: int) -> str:
        blob = self._client.bucket(bucket).blob(key)
        return blob.generate_signed_url(
            expiration=timedelta(seconds=expires),
            method='GET',
            version='v4',
        )

    def check_permissions(self, bucket: str) -> dict:
        checks = {'list': False, 'get': False, 'put': False, 'delete': False}
        try:
            list(self._client.list_blobs(bucket, max_results=1))
            checks['list'] = True
        except GoogleCloudError:
            pass

        checks['get'] = checks['list']

        try:
            blob = self._client.bucket(bucket).blob('__bucketlens_permission_check__')
            blob.upload_from_string(b'')
            blob.delete()
            checks['put'] = True
            checks['delete'] = True
        except GoogleCloudError:
            pass

        return checks


# ---------------------------------------------------------------------------
# AzureProvider — wraps azure-storage-blob
# ---------------------------------------------------------------------------

class AzureProvider(StorageProvider):
    def __init__(self):
        if not AZURE_AVAILABLE:
            raise RuntimeError(
                "azure-storage-blob not installed. "
                "Run: pip install azure-storage-blob azure-identity"
            )
        conn_str = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
        account = os.environ.get('AZURE_STORAGE_ACCOUNT')

        if conn_str:
            self._client = BlobServiceClient.from_connection_string(conn_str)
        elif account:
            credential = DefaultAzureCredential()
            self._client = BlobServiceClient(
                account_url=f"https://{account}.blob.core.windows.net",
                credential=credential,
            )
        else:
            raise RuntimeError(
                "Set AZURE_STORAGE_CONNECTION_STRING or "
                "AZURE_STORAGE_ACCOUNT env var"
            )

    def list_buckets(self) -> list:
        # In Azure, buckets = containers
        containers = self._client.list_containers()
        return sorted(c['name'] for c in containers)

    def list_objects(self, bucket: str, prefix: str = '') -> dict:
        container = self._client.get_container_client(bucket)
        folders = set()
        objects = []

        blobs = container.walk_blobs(name_starts_with=prefix, delimiter='/')

        for blob in blobs:
            if hasattr(blob, 'prefix'):
                folders.add(blob.prefix)
            else:
                key = blob.name
                if key.endswith('/'):
                    continue
                objects.append({
                    'key': key,
                    'size': blob.size,
                    'last_modified': blob.last_modified.isoformat(),
                    'browsable': is_browsable(key),
                    'media_type': media_type(key),
                })

        return {
            'folders': sorted(folders),
            'objects': objects,
            'versioning_enabled': False,
        }

    def get_object(self, bucket: str, key: str) -> tuple:
        blob = self._client.get_blob_client(container=bucket, blob=key)
        download = blob.download_blob()
        content_type = (
            download.properties.content_settings.content_type
            or mimetypes.guess_type(key)[0]
            or 'application/octet-stream'
        )
        content_length = download.properties.size
        return download.chunks(), content_type, content_length

    def put_object(self, bucket: str, key: str,
                   data: bytes, content_type: str) -> None:
        blob = self._client.get_blob_client(container=bucket, blob=key)
        blob.upload_blob(
            data,
            content_settings=ContentSettings(content_type=content_type),
            overwrite=True,
        )

    def delete_object(self, bucket: str, key: str) -> None:
        blob = self._client.get_blob_client(container=bucket, blob=key)
        blob.delete_blob()

    def get_object_metadata(self, bucket: str, key: str) -> dict:
        blob = self._client.get_blob_client(container=bucket, blob=key)
        props = blob.get_blob_properties()
        return {
            'size': props.size,
            'last_modified': props.last_modified.isoformat(),
            'content_type': props.content_settings.content_type,
        }

    def generate_presigned_url(self, bucket: str,
                                key: str, expires: int) -> str:
        account_name = self._client.account_name
        account_key = getattr(self._client.credential, 'account_key', None)

        if not account_key:
            raise NotImplementedError(
                "Presigned URLs require a connection string with account key. "
                "DefaultAzureCredential does not support SAS token generation."
            )

        sas = generate_blob_sas(
            account_name=account_name,
            container_name=bucket,
            blob_name=key,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires),
        )
        return f"https://{account_name}.blob.core.windows.net/{bucket}/{key}?{sas}"

    def check_permissions(self, bucket: str) -> dict:
        checks = {'list': False, 'get': False, 'put': False, 'delete': False}
        try:
            container = self._client.get_container_client(bucket)
            list(container.list_blobs(max_results=1))
            checks['list'] = True
        except AzureError:
            pass

        checks['get'] = checks['list']

        try:
            test_blob = self._client.get_blob_client(
                container=bucket,
                blob='__bucketlens_permission_check__',
            )
            test_blob.upload_blob(b'', overwrite=True)
            test_blob.delete_blob()
            checks['put'] = True
            checks['delete'] = True
        except AzureError:
            pass

        return checks


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict = {}


def get_provider(provider_type: str = 'aws') -> StorageProvider:
    """Returns a cached StorageProvider instance for the given provider type."""
    key = provider_type
    if key not in _PROVIDERS:
        if provider_type == 'aws':
            profile = os.environ.get('AWS_PROFILE')
            region = os.environ.get('AWS_DEFAULT_REGION')
            _PROVIDERS[key] = S3Provider(profile, region)
        elif provider_type == 'azure':
            _PROVIDERS[key] = AzureProvider()
        elif provider_type == 'gcp':
            _PROVIDERS[key] = GCPProvider()
        else:
            abort(400, description=f"Unknown provider: {provider_type}")
    return _PROVIDERS[key]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    """Check if credentials are configured for the given provider."""
    provider_type = request.args.get("provider", "aws")
    try:
        p = get_provider(provider_type)
        p.list_buckets()
        return jsonify({"ok": True, "provider": provider_type})
    except NotImplementedError as exc:
        return jsonify({"ok": False, "provider": provider_type, "error": str(exc)})
    except Exception as exc:
        return jsonify({"ok": False, "provider": provider_type, "error": str(exc)})


@app.route("/api/buckets")
def list_buckets():
    """List all buckets the caller has access to."""
    provider_type = request.args.get("provider", "aws")
    try:
        p = get_provider(provider_type)
        names = p.list_buckets()
        return jsonify({"buckets": names, "provider": provider_type})
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/objects")
def list_objects():
    """List objects in a bucket with optional prefix."""
    bucket = request.args.get("bucket")
    prefix = request.args.get("prefix", "")
    provider_type = request.args.get("provider", "aws")
    if not bucket:
        return jsonify({"error": "bucket is required"}), 400

    try:
        p = get_provider(provider_type)
        result = p.list_objects(bucket, prefix)
        return jsonify({
            "bucket": bucket,
            "prefix": prefix,
            "folders": result["folders"],
            "objects": result["objects"],
        })
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except _STORAGE_ERRORS as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/object")
def get_object():
    """Stream a storage object's bytes to the browser."""
    bucket = request.args.get("bucket")
    key = request.args.get("key")
    provider_type = request.args.get("provider", "aws")
    if not bucket or not key:
        return jsonify({"error": "bucket and key are required"}), 400

    force_download = request.args.get("download") == "1"
    disposition = "attachment" if force_download else "inline"
    is_image = media_type(key) == "image"
    use_cache = PILLOW_AVAILABLE and is_image and not force_download

    try:
        p = get_provider(provider_type)

        # Fetch metadata first for ETag / conditional 304 / cache key
        try:
            meta = p.get_object_metadata(bucket, key)
            etag = hashlib.md5(
                f"{key}:{meta.get('size', '')}:{meta.get('last_modified', '')}".encode()
            ).hexdigest()
            file_size = meta.get("size", 0)
        except Exception:
            etag = hashlib.md5(key.encode()).hexdigest()
            file_size = 0
            meta = {}

        # 304 Not Modified — respond before fetching the body (saves cloud cost)
        if_none_match = request.headers.get("If-None-Match", "").strip('"')
        if etag and if_none_match == etag:
            return make_response('', 304)

        # Check thumbnail cache (server-side)
        if use_cache and file_size < 20 * 1024 * 1024:
            cache_key = get_cache_key(provider_type, bucket, key, etag)
            cached_data, cached_ct = get_cached_thumb(cache_key)

            if cached_data:
                response = make_response(cached_data)
                response.headers['Content-Type'] = 'image/jpeg'
                response.headers['Cache-Control'] = 'private, max-age=3600, must-revalidate'
                response.headers['ETag'] = f'"{etag}"'
                response.headers['X-Cache'] = 'HIT'
                return response

        # Cache miss or not cacheable — fetch from provider
        chunks, content_type, content_length = p.get_object(bucket, key)

        # For cacheable images under 20MB: read, resize, cache, return
        if use_cache and file_size < 20 * 1024 * 1024:
            raw = b''.join(chunks)
            thumb = make_thumbnail(raw, content_type)

            if thumb:
                save_thumb_cache(cache_key, thumb)
                response = make_response(thumb)
                response.headers['Content-Type'] = 'image/jpeg'
                response.headers['Cache-Control'] = 'private, max-age=3600, must-revalidate'
                response.headers['ETag'] = f'"{etag}"'
                response.headers['X-Cache'] = 'MISS'
                return response
            else:
                # Pillow failed — serve raw bytes
                chunks = iter([raw])

        # Non-image, large file, or no Pillow — stream as-is
        headers = {
            "Content-Disposition": f'{disposition}; filename="{os.path.basename(key)}"',
            "Content-Length": str(content_length or ''),
            "Cache-Control": "private, max-age=3600, must-revalidate",
            "ETag": f'"{etag}"',
            "X-Cache": "BYPASS",
        }

        last_modified = meta.get("last_modified")
        if last_modified:
            try:
                dt = datetime.fromisoformat(last_modified)
                headers["Last-Modified"] = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")
            except (ValueError, TypeError):
                pass

        return Response(
            stream_with_context(chunks),
            content_type=content_type,
            headers=headers,
        )
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except _STORAGE_ERRORS as exc:
        return jsonify({"error": str(exc)}), 404


@app.route("/api/upload", methods=["POST"])
def upload_object():
    """Upload one or more files to a bucket/prefix."""
    bucket = request.form.get("bucket")
    prefix = request.form.get("prefix", "")
    provider_type = request.form.get("provider", "aws")
    if not bucket:
        return jsonify({"error": "bucket is required"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files provided"}), 400

    try:
        p = get_provider(provider_type)
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501

    uploaded = []
    errors = []
    for f in files:
        key = prefix + f.filename
        ct = f.content_type or mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
        try:
            p.put_object(bucket, key, f.read(), ct)
            uploaded.append(key)
        except _STORAGE_ERRORS as exc:
            errors.append({"file": f.filename, "error": str(exc)})

    return jsonify({"uploaded": uploaded, "errors": errors})


@app.route("/api/delete", methods=["POST"])
def delete_object():
    """Delete an object from a bucket."""
    data = request.get_json(silent=True) or {}
    bucket = data.get("bucket")
    key = data.get("key")
    provider_type = data.get("provider", "aws")
    if not bucket or not key:
        return jsonify({"error": "bucket and key are required"}), 400

    ua = request.headers.get("User-Agent")

    try:
        p = get_provider(provider_type)
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501

    file_size = None
    try:
        meta = p.get_object_metadata(bucket, key)
        file_size = meta.get("size")
    except _STORAGE_ERRORS:
        pass

    try:
        p.delete_object(bucket, key)
        ts = datetime.now(timezone.utc).isoformat()
        audit.log_delete(bucket, key, file_size, "success",
                         provider=provider_type, user_agent=ua)
        return jsonify({"deleted": key, "timestamp": ts})
    except _STORAGE_ERRORS as exc:
        audit.log_delete(bucket, key, file_size, "error", str(exc),
                         provider=provider_type, user_agent=ua)
        return jsonify({"error": str(exc)}), 500


@app.route("/api/presign")
def presign_object():
    """Generate a presigned URL for a storage object."""
    bucket = request.args.get("bucket")
    key = request.args.get("key")
    provider_type = request.args.get("provider", "aws")
    try:
        expires = min(int(request.args.get("expires", 3600)), 86400)
    except ValueError:
        expires = 3600

    if not bucket or not key:
        return jsonify({"error": "bucket and key required"}), 400

    try:
        p = get_provider(provider_type)
        url = p.generate_presigned_url(bucket, key, expires)
        return jsonify({
            "url": url,
            "expires_in": expires,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expires)).isoformat(),
        })
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except _STORAGE_ERRORS as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/preview")
def preview_object():
    """Fetch and return a text file's content for in-browser preview (max 1MB)."""
    bucket = request.args.get("bucket")
    key = request.args.get("key")
    provider_type = request.args.get("provider", "aws")
    if not bucket or not key:
        return jsonify({"error": "bucket and key are required"}), 400

    try:
        p = get_provider(provider_type)
        meta = p.get_object_metadata(bucket, key)
        size = meta["size"]

        if size > 1048576:
            return jsonify({
                "error": "file too large to preview",
                "size": size,
                "download_only": True,
            }), 413

        chunks, content_type, _ = p.get_object(bucket, key)
        content = b"".join(chunks)

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return jsonify({
                "error": "binary file — cannot preview",
                "download_only": True,
            }), 415

        return jsonify({
            "key": key,
            "content": text,
            "size": size,
            "content_type": content_type,
        })
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except _STORAGE_ERRORS as exc:
        return jsonify({"error": str(exc)}), 404


@app.route("/api/download-zip", methods=["POST"])
def download_zip():
    """Stream a ZIP of selected objects."""
    data = request.get_json(silent=True) or {}
    bucket = data.get("bucket")
    keys = data.get("keys", [])
    provider_type = data.get("provider", "aws")

    if not bucket or not keys:
        return jsonify({"error": "bucket and keys required"}), 400
    if len(keys) > 500:
        return jsonify({"error": "max 500 files per download"}), 400

    try:
        p = get_provider(provider_type)
    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501

    def generate_zip():
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for key in keys:
                try:
                    chunks, _, _ = p.get_object(bucket, key)
                    filename = key.split('/')[-1]
                    zf.writestr(filename, b"".join(chunks))
                except _STORAGE_ERRORS:
                    pass
        buf.seek(0)
        yield buf.read()

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    filename = f"bucketlens-{bucket}-{timestamp}.zip"

    return Response(
        stream_with_context(generate_zip()),
        content_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


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


@app.route("/api/exif")
def get_exif():
    """Extract EXIF metadata and basic image info for an image file."""
    bucket = request.args.get("bucket")
    key = request.args.get("key")
    provider_type = request.args.get("provider", "aws")

    if not bucket or not key:
        return jsonify({"error": "bucket and key required"}), 400

    if not PILLOW_AVAILABLE:
        return jsonify({"error": "Pillow not installed", "install": "pip install Pillow"}), 501

    try:
        p = get_provider(provider_type)
        meta = p.get_object_metadata(bucket, key)
        etag = hashlib.md5(
            f"{key}:{meta.get('size', '')}:{meta.get('last_modified', '')}".encode()
        ).hexdigest()

        # Use cached thumbnail bytes if available, else fetch full image
        cache_key = get_cache_key(provider_type, bucket, key, etag)
        cached_path = CACHE_DIR / cache_key
        if cached_path.exists():
            try:
                raw = cached_path.read_bytes()
            except OSError:
                raw = None
        else:
            raw = None

        if raw is None:
            if meta.get("size", 0) > 20 * 1024 * 1024:
                return jsonify({"error": "file too large for EXIF", "size": meta.get("size")}), 413
            chunks_iter, _, _ = p.get_object(bucket, key)
            raw = b"".join(chunks_iter)

        from PIL import Image as _PIL
        from PIL.ExifTags import TAGS, GPSTAGS

        img = _PIL.open(_io.BytesIO(raw))

        result = {
            "filename": key.split("/")[-1],
            "key": key,
            "bucket": bucket,
            "provider": provider_type,
            "width": img.width,
            "height": img.height,
            "format": img.format or "unknown",
            "mode": img.mode,
            "aspect_ratio": f"{img.width}:{img.height}",
            "file_size": meta.get("size", 0),
            "last_modified": meta.get("last_modified", ""),
            "content_type": meta.get("content_type", ""),
            "exif": {},
            "gps": None,
        }

        WANTED = {
            "DateTime", "DateTimeOriginal", "DateTimeDigitized",
            "Make", "Model", "Software", "Artist", "Copyright",
            "ExposureTime", "FNumber", "ISOSpeedRatings",
            "ShutterSpeedValue", "ApertureValue", "BrightnessValue",
            "ExposureBiasValue", "MaxApertureValue", "MeteringMode",
            "Flash", "FocalLength", "ColorSpace",
            "PixelXDimension", "PixelYDimension",
            "ExifImageWidth", "ExifImageHeight",
            "Orientation", "XResolution", "YResolution",
            "ResolutionUnit", "WhiteBalance", "DigitalZoomRatio",
            "FocalLengthIn35mmFilm", "SceneCaptureType",
            "LensModel", "LensMake", "ExposureMode", "ExposureProgram",
        }

        exif_raw = img._getexif() if hasattr(img, "_getexif") else None
        if exif_raw:
            gps_info = {}
            for tag_id, value in exif_raw.items():
                tag = TAGS.get(tag_id, str(tag_id))
                if tag == "GPSInfo":
                    for gps_tag_id, gps_val in value.items():
                        gps_info[GPSTAGS.get(gps_tag_id, str(gps_tag_id))] = str(gps_val)
                    continue
                if tag not in WANTED:
                    continue
                if isinstance(value, bytes):
                    continue
                if hasattr(value, "numerator"):
                    try:
                        value = round(float(value), 4)
                    except Exception:
                        value = str(value)
                elif isinstance(value, tuple):
                    value = str(value)
                result["exif"][tag] = value

            if gps_info:
                try:
                    def _dms_to_dd(dms, ref):
                        parts = [float(x) for x in str(dms).strip("()").split(",")]
                        dd = parts[0] + parts[1] / 60 + parts[2] / 3600
                        if ref in ("S", "W"):
                            dd = -dd
                        return round(dd, 7)
                    lat = _dms_to_dd(gps_info.get("GPSLatitude", ""), gps_info.get("GPSLatitudeRef", "N"))
                    lon = _dms_to_dd(gps_info.get("GPSLongitude", ""), gps_info.get("GPSLongitudeRef", "E"))
                    result["gps"] = {"lat": lat, "lon": lon,
                                     "maps_url": f"https://maps.google.com/?q={lat},{lon}"}
                except Exception:
                    result["gps"] = None

        # Human-friendly formatting
        if "ExposureTime" in result["exif"]:
            et = result["exif"]["ExposureTime"]
            if isinstance(et, float) and et < 1:
                result["exif"]["ExposureTime"] = f"1/{round(1/et)}s"
            else:
                result["exif"]["ExposureTime"] = f"{et}s"
        if "FNumber" in result["exif"]:
            result["exif"]["FNumber"] = f"f/{result['exif']['FNumber']}"
        if "FocalLength" in result["exif"]:
            result["exif"]["FocalLength"] = f"{result['exif']['FocalLength']}mm"

        return jsonify(result)

    except NotImplementedError as exc:
        return jsonify({"error": str(exc)}), 501
    except _STORAGE_ERRORS as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": f"EXIF extraction failed: {exc}"}), 500


@app.route("/api/reset-provider", methods=["POST"])
def reset_provider():
    """Clear the provider cache. Call when switching providers or AWS_PROFILE."""
    _PROVIDERS.clear()
    return jsonify({"ok": True, "message": "provider cache cleared"})


@app.route("/api/cache/stats")
def cache_stats():
    """Return thumbnail cache statistics."""
    try:
        files = list(CACHE_DIR.iterdir())
        total_bytes = sum(f.stat().st_size for f in files)
        return jsonify({
            "cached_thumbs": len(files),
            "total_size": total_bytes,
            "total_size_human": _fmt_size(total_bytes),
            "cache_dir": str(CACHE_DIR),
            "limit_bytes": CACHE_MAX_BYTES,
            "pillow_available": PILLOW_AVAILABLE,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/cache/clear", methods=["DELETE"])
def cache_clear():
    """Clear all cached thumbnails."""
    try:
        count = 0
        for f in CACHE_DIR.iterdir():
            f.unlink(missing_ok=True)
            count += 1
        return jsonify({
            "cleared": count,
            "message": f"Removed {count} cached thumbnails",
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("BucketLens_PORT", 8080))
    print(f"\n☁️  BucketLens running at http://127.0.0.1:{port}\n")
    print("   Using AWS credentials from your default profile.")
    print("   Set AWS_PROFILE=<name> to use a different profile.\n")
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=port, debug=False)
