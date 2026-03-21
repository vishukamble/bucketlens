"""AWS S3 provider — Flask Blueprint."""

import os
import mimetypes
import urllib.parse
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, Response, stream_with_context
import boto3
from botocore.exceptions import ClientError, NoCredentialsError, BotoCoreError

import audit
from app import is_browsable, media_type

aws_bp = Blueprint("aws", __name__)

_s3_client = None


def get_s3_client():
    """Return a cached boto3 S3 client."""
    global _s3_client
    if _s3_client is None:
        try:
            profile = os.environ.get('AWS_PROFILE')
            region = os.environ.get('AWS_DEFAULT_REGION')
            session = boto3.Session(profile_name=profile, region_name=region)
            _s3_client = session.client('s3')
        except (NoCredentialsError, BotoCoreError) as exc:
            from flask import abort
            abort(500, description=f"AWS credential error: {exc}")
    return _s3_client


@aws_bp.route("/api/buckets")
def list_buckets():
    """List all S3 buckets the caller has access to."""
    try:
        s3 = get_s3_client()
        resp = s3.list_buckets()
        names = sorted(b["Name"] for b in resp.get("Buckets", []))
        return jsonify({"buckets": names})
    except (ClientError, NoCredentialsError, BotoCoreError) as exc:
        return jsonify({"error": str(exc)}), 500


@aws_bp.route("/api/objects")
def list_objects():
    """List objects in an S3 bucket with optional prefix."""
    bucket = request.args.get("bucket")
    prefix = request.args.get("prefix", "")
    if not bucket:
        return jsonify({"error": "bucket is required"}), 400

    try:
        s3 = get_s3_client()
        objects = []
        folders = set()

        paginator = s3.get_paginator("list_objects_v2")
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

        return jsonify({
            "bucket": bucket,
            "prefix": prefix,
            "folders": sorted(folders),
            "objects": objects,
        })
    except (ClientError, BotoCoreError) as exc:
        return jsonify({"error": str(exc)}), 500


@aws_bp.route("/api/object")
def get_object():
    """Stream an S3 object's bytes to the browser."""
    bucket = request.args.get("bucket")
    key = request.args.get("key")
    if not bucket or not key:
        return jsonify({"error": "bucket and key are required"}), 400

    force_download = request.args.get("download") == "1"
    disposition = "attachment" if force_download else "inline"

    try:
        s3 = get_s3_client()
        resp = s3.get_object(Bucket=bucket, Key=key)
        content_type = (
            resp.get("ContentType")
            or mimetypes.guess_type(key)[0]
            or "application/octet-stream"
        )
        content_length = resp.get("ContentLength", "")

        def generate():
            for chunk in resp["Body"].iter_chunks(chunk_size=8192):
                yield chunk

        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                "Content-Disposition": f"{disposition}; filename*=UTF-8''{urllib.parse.quote(os.path.basename(key))}",
                "Content-Length": str(content_length),
            },
        )
    except ClientError as exc:
        return jsonify({"error": str(exc)}), 404


@aws_bp.route("/api/upload", methods=["POST"])
def upload_object():
    """Upload one or more files to an S3 bucket."""
    bucket = request.form.get("bucket")
    prefix = request.form.get("prefix", "")
    if not bucket:
        return jsonify({"error": "bucket is required"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files provided"}), 400

    s3 = get_s3_client()
    uploaded = []
    errors = []
    for f in files:
        key = prefix + f.filename
        ct = f.content_type or mimetypes.guess_type(f.filename)[0] or "application/octet-stream"
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=f.read(), ContentType=ct)
            uploaded.append(key)
        except ClientError as exc:
            errors.append({"file": f.filename, "error": str(exc)})

    return jsonify({"uploaded": uploaded, "errors": errors})


@aws_bp.route("/api/delete", methods=["POST"])
def delete_object():
    """Delete an object from an S3 bucket."""
    data = request.get_json(silent=True) or {}
    bucket = data.get("bucket")
    key = data.get("key")
    if not bucket or not key:
        return jsonify({"error": "bucket and key are required"}), 400

    ua = request.headers.get("User-Agent")

    try:
        s3 = get_s3_client()

        # Get file size for audit log
        file_size = None
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            file_size = head.get("ContentLength")
        except ClientError:
            pass

        s3.delete_object(Bucket=bucket, Key=key)
        ts = datetime.now(timezone.utc).isoformat()
        audit.log_delete(bucket, key, file_size, "success",
                         provider="aws", user_agent=ua)
        return jsonify({"deleted": key, "timestamp": ts})
    except ClientError as exc:
        audit.log_delete(bucket, key, None, "error", str(exc),
                         provider="aws", user_agent=ua)
        return jsonify({"error": str(exc)}), 500
