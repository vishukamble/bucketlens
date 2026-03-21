# GCP Cloud Storage — not yet implemented

from flask import Blueprint, jsonify

gcp_bp = Blueprint("gcp", __name__)


@gcp_bp.route("/api/gcp/buckets")
def list_buckets():
    return jsonify({"error": "GCP support not yet implemented"}), 501
