# Changelog

All notable changes to BucketLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Provider selection modal (AWS / Azure / GCP)
- Credential health check endpoint (/api/health)
- 2-step delete: warning modal + bucket-name confirmation page
- Audit log: every delete written to SQLite + plaintext (bucketlens_audit.db + bucketlens_audit.log)
- Neon Cyber theme: Electric Violet + Vibrant Emerald
- Group by date modified / file size / file type (grid view)
- Sort by name / size / date modified (list view)
- Search/filter bar with "/" keyboard shortcut
- Copy S3 URI on hover (s3://bucket/key)
- Keyboard shortcuts: G, /, Ctrl+A, Ctrl+C, Ctrl+D, ?
- Bulk download as ZIP (/api/download-zip)
- Presigned URL generator with expiry selector
- Streaming proxy: S3 bytes streamed in 8KB chunks, never fully loaded into memory
- Bucket selection modal explaining proxy pattern + S3 costs
- Werkzeug request log suppressed in production mode

## [0.1.0] - 2025-03-16

### Added
- Initial release
- S3 bucket browser with lazy-loading thumbnail grid
- Folder navigation with breadcrumb path
- Lightbox viewer with arrow key navigation
- Drag and drop upload with progress toast
- Multi-file delete with confirmation
- List view with file size and date metadata
- Video playback support (mp4, mov, webm, avi, mkv)
- Grid/list view toggle
- Thumbnail size slider
- AWS credential chain support (reads ~/.aws/credentials)
- AWS_PROFILE and BucketLens_PORT env var support
