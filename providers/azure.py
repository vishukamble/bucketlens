"""Azure Blob Storage provider — Flask Blueprint."""

import os
import mimetypes
import urllib.parse

from flask import Blueprint, jsonify, request, Response, stream_with_context
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import AzureError

from app import is_browsable, media_type

azure_bp = Blueprint("azure", __name__)

_azure_client = None


def get_azure_client():
    """Return a cached BlobServiceClient using DefaultAzureCredential."""
    global _azure_client
    if _azure_client is None:
        account = os.environ.get('AZURE_STORAGE_ACCOUNT')
        if not account:
            return None
        credential = DefaultAzureCredential()
        _azure_client = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=credential,
        )
    return _azure_client


@azure_bp.route("/api/azure/containers")
def list_containers():
    """List all containers in the Azure storage account."""
    client = get_azure_client()
    if client is None:
        return jsonify({"error": "AZURE_STORAGE_ACCOUNT env var not set"}), 500

    try:
        containers = client.list_containers()
        names = sorted(c['name'] for c in containers)
        return jsonify({"containers": names})
    except AzureError as exc:
        return jsonify({"error": str(exc)}), 500


@azure_bp.route("/api/azure/objects")
def list_objects():
    """List blobs and virtual folders in an Azure container."""
    container_name = request.args.get("container")
    prefix = request.args.get("prefix", "")
    if not container_name:
        return jsonify({"error": "container is required"}), 400

    client = get_azure_client()
    if client is None:
        return jsonify({"error": "AZURE_STORAGE_ACCOUNT env var not set"}), 500

    try:
        container = client.get_container_client(container_name)
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

        return jsonify({
            "container": container_name,
            "prefix": prefix,
            "folders": sorted(folders),
            "objects": objects,
        })
    except AzureError as exc:
        return jsonify({"error": str(exc)}), 500


@azure_bp.route("/api/azure/object")
def get_object():
    """Stream an Azure blob's bytes to the browser."""
    container_name = request.args.get("container")
    key = request.args.get("key")
    if not container_name or not key:
        return jsonify({"error": "container and key are required"}), 400

    client = get_azure_client()
    if client is None:
        return jsonify({"error": "AZURE_STORAGE_ACCOUNT env var not set"}), 500

    try:
        blob_client = client.get_blob_client(container=container_name, blob=key)
        download = blob_client.download_blob()
        content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"

        def generate():
            for chunk in download.chunks():
                yield chunk

        return Response(
            stream_with_context(generate()),
            mimetype=content_type,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{urllib.parse.quote(os.path.basename(key))}"},
        )
    except AzureError as exc:
        return jsonify({"error": str(exc)}), 500
