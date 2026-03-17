// ── State ──
let currentBucket = "";
let currentPrefix = "";
let currentObjects = [];
let currentFolders = [];
let browsableObjects = [];
let selectedKeys = new Set();
let currentView = "grid";
let lightboxIndex = -1;
let currentProvider = "";
let sortField = "name";
let sortDir = "asc";
let groupBy = "none";
let searchQuery = "";
let exifPanelOpen = false;
let exifCurrentKey = null;

// ── Elements ──
const $bucket = document.getElementById("bucketSelect");
const $content = document.getElementById("content");
const $breadcrumb = document.getElementById("breadcrumb");
const $count = document.getElementById("objectCount");
const $uploadBtn = document.getElementById("uploadBtn");
const $deleteBtn = document.getElementById("deleteBtn");
const $downloadBtn = document.getElementById("downloadBtn");
const $fileInput = document.getElementById("fileInput");
const $sizeSlider = document.getElementById("sizeSlider");
const $lightbox = document.getElementById("lightbox");
const $lightboxContent = document.getElementById("lightboxContent");
const $lightboxInfo = document.getElementById("lightboxInfo");
const $dropzone = document.getElementById("dropzone");
const $dropzoneTarget = document.getElementById("dropzoneTarget");
const $uploadToast = document.getElementById("uploadToast");
const $uploadFill = document.getElementById("uploadFill");
const $uploadStatus = document.getElementById("uploadStatus");
const $providerModal = document.getElementById("providerModal");
const $setupModal = document.getElementById("setupModal");
const $credStatus = document.getElementById("credStatus");
const $credActions = document.getElementById("credActions");
const $providerPill = document.getElementById("providerPill");
const $switchProviderBtn = document.getElementById("switchProviderBtn");
const $sortControls = document.getElementById("sortControls");
const $sortFieldEl = document.getElementById("sortField");
const $sortDirBtn = document.getElementById("sortDir");
const $groupControls = document.getElementById("groupControls");
const $groupByEl = document.getElementById("groupBy");
const $searchInput = document.getElementById("searchInput");

// ── Init ──
(function init() { initProvider(); })();

$sortFieldEl.addEventListener("change", () => {
  sortField = $sortFieldEl.value;
  renderContent(currentFolders, currentObjects);
});
$sortDirBtn.addEventListener("click", () => {
  sortDir = sortDir === "asc" ? "desc" : "asc";
  $sortDirBtn.textContent = sortDir === "asc" ? "↑" : "↓";
  renderContent(currentFolders, currentObjects);
});

$groupByEl.addEventListener("change", () => {
  groupBy = $groupByEl.value;
  renderContent(currentFolders, currentObjects);
});

$searchInput.addEventListener("input", e => {
  searchQuery = e.target.value.trim().toLowerCase();
  const filtered = getFilteredObjects();
  renderContent(currentFolders, filtered);
  if (searchQuery) {
    $count.textContent = `${filtered.length} of ${currentObjects.length} files`;
  } else {
    updateCount(currentFolders.length, currentObjects.length, browsableObjects.length);
  }
});

async function loadBuckets() {
  try {
    const resp = await fetch(`/api/buckets?provider=${enc(currentProvider)}`);
    const data = await resp.json();
    if (data.error) { showToast(data.error, "error"); return; }
    data.buckets.forEach(b => {
      const opt = document.createElement("option");
      opt.value = b; opt.textContent = b;
      $bucket.appendChild(opt);
    });
  } catch (err) {
    showToast("Failed to connect. Is Flask running?", "error");
  }
}

// ── Events ──
$bucket.addEventListener("change", () => {
  currentBucket = $bucket.value;
  currentPrefix = "";
  selectedKeys.clear();
  if (currentBucket) {
    $uploadBtn.style.display = "";
    if (localStorage.getItem("bl_seen_bucket_" + currentBucket)) {
      loadObjects();
    } else {
      openBucketInfoModal(currentBucket);
    }
  }
});

$sizeSlider.addEventListener("input", () => {
  document.documentElement.style.setProperty("--thumb-size", $sizeSlider.value + "px");
});

$fileInput.addEventListener("change", () => {
  if ($fileInput.files.length) uploadFiles($fileInput.files);
});

// Drag-and-drop
let dragCounter = 0;
document.addEventListener("dragenter", e => {
  e.preventDefault(); dragCounter++;
  if (currentBucket) {
    $dropzone.classList.add("active");
    $dropzoneTarget.textContent = `to ${currentBucket}/${currentPrefix}`;
  }
});
document.addEventListener("dragleave", e => {
  e.preventDefault(); dragCounter--;
  if (dragCounter <= 0) { $dropzone.classList.remove("active"); dragCounter = 0; }
});
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => {
  e.preventDefault(); dragCounter = 0;
  $dropzone.classList.remove("active");
  if (currentBucket && e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});

// Keyboard
document.addEventListener("keydown", e => {
  // Lightbox — always active
  if ($lightbox.classList.contains("open")) {
    if (e.key === "Escape") closeLightbox();
    if (e.key === "ArrowLeft") navLightbox(-1);
    if (e.key === "ArrowRight") navLightbox(1);
    if (e.key === "i" || e.key === "I") {
      const mediaObjects = browsableObjects.filter(o => o.media_type === "image" || o.media_type === "video");
      if (mediaObjects[lightboxIndex]) openExifPanel(mediaObjects[lightboxIndex].key);
    }
    return;
  }
  // Shortcuts modal close
  if (e.key === "Escape" && document.getElementById("shortcutsModal").classList.contains("open")) {
    closeShortcutsModal(); return;
  }
  // File preview modal close
  if (e.key === "Escape" && document.getElementById("filePreviewModal").classList.contains("open")) {
    closeFilePreview(); return;
  }
  // Search input — Escape clears before typing guard
  if (e.key === "Escape" && document.activeElement === $searchInput) {
    $searchInput.value = "";
    searchQuery = "";
    renderContent(currentFolders, currentObjects);
    updateCount(currentFolders.length, currentObjects.length, browsableObjects.length);
    $searchInput.blur(); return;
  }
  // Guard: skip shortcuts when typing in inputs
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  if (typing) return;

  if (e.key === "c" && e.ctrlKey && selectedKeys.size) {
    const prefix = currentProvider === "gcp" ? "gs" : currentProvider === "azure" ? "https" : "s3";
    const uris = [...selectedKeys].map(k => {
      if (currentProvider === "azure") return `https://${currentBucket}.blob.core.windows.net/${k}`;
      return `${prefix}://${currentBucket}/${k}`;
    }).join("\n");
    navigator.clipboard.writeText(uris).then(() => {
      showToast(`copied ${selectedKeys.size} S3 URI${selectedKeys.size > 1 ? "s" : ""}`, "success");
    }).catch(() => {
      const el = document.createElement("textarea");
      el.value = uris;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
      showToast(`copied ${selectedKeys.size} S3 URI${selectedKeys.size > 1 ? "s" : ""}`, "success");
    });
    return;
  }
  if (e.key === "d" && e.ctrlKey && selectedKeys.size) {
    e.preventDefault();
    downloadSelected(); return;
  }
  if (e.key === "a" && e.ctrlKey) {
    e.preventDefault();
    browsableObjects.forEach(o => selectedKeys.add(o.key));
    renderContent(currentFolders, getFilteredObjects());
    updateSelectionBtns(); return;
  }
  if (e.key === "Escape" && selectedKeys.size) {
    selectedKeys.clear();
    renderContent(currentFolders, getFilteredObjects());
    updateSelectionBtns(); return;
  }
  if (e.key === "/") {
    e.preventDefault();
    $searchInput.focus(); return;
  }
  if (e.key === "g" || e.key === "G") {
    setView(currentView === "grid" ? "list" : "grid"); return;
  }
  if (e.key === "?") {
    openShortcutsModal(); return;
  }
});

// ── Data fetching ──
function getFilteredObjects() {
  if (!searchQuery) return currentObjects;
  return currentObjects.filter(o =>
    o.key.split("/").pop().toLowerCase().includes(searchQuery)
  );
}

async function loadObjects() {
  searchQuery = "";
  $searchInput.value = "";
  showLoading();
  try {
    const resp = await fetch(`/api/objects?bucket=${enc(currentBucket)}&prefix=${enc(currentPrefix)}&provider=${enc(currentProvider)}`);
    const data = await resp.json();
    if (data.error) { showToast(data.error, "error"); return; }

    currentObjects = data.objects || [];
    currentFolders = data.folders || [];
    browsableObjects = currentObjects.filter(o => o.browsable);
    updateBreadcrumb();
    updateCount(currentFolders.length, currentObjects.length, browsableObjects.length);
    renderContent(currentFolders, currentObjects);
    updateSelectionBtns();
  } catch (err) {
    showToast("Failed to load objects", "error");
  }
}

// ── Sort ──
function sortObjects(objects) {
  objects.sort((a, b) => {
    let va, vb;
    if (sortField === "name") {
      va = a.key.split("/").pop().toLowerCase();
      vb = b.key.split("/").pop().toLowerCase();
    } else if (sortField === "size") {
      va = a.size; vb = b.size;
    } else {
      va = a.last_modified; vb = b.last_modified;
    }
    if (va < vb) return sortDir === "asc" ? -1 : 1;
    if (va > vb) return sortDir === "asc" ? 1 : -1;
    return 0;
  });
}

// ── Group ──
function groupObjects(objects) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const weekAgo = new Date(today); weekAgo.setDate(today.getDate() - 7);
  const monthAgo = new Date(today); monthAgo.setDate(today.getDate() - 30);

  if (groupBy === "date-modified") {
    const buckets = ["today", "yesterday", "this week", "this month", "older"];
    const g = {}; buckets.forEach(b => { g[b] = []; });
    objects.forEach(obj => {
      const d = new Date(obj.last_modified);
      const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      if (day >= today) g["today"].push(obj);
      else if (day >= yesterday) g["yesterday"].push(obj);
      else if (d >= weekAgo) g["this week"].push(obj);
      else if (d >= monthAgo) g["this month"].push(obj);
      else g["older"].push(obj);
    });
    return buckets.filter(b => g[b].length).map(b => ({ label: b, objects: g[b] }));
  }

  if (groupBy === "size") {
    const buckets = ["large  > 10 MB", "medium  1 MB – 10 MB", "small  100 KB – 1 MB", "tiny  < 100 KB"];
    const g = {}; buckets.forEach(b => { g[b] = []; });
    objects.forEach(obj => {
      if (obj.size > 10 * 1024 * 1024) g["large  > 10 MB"].push(obj);
      else if (obj.size > 1024 * 1024) g["medium  1 MB – 10 MB"].push(obj);
      else if (obj.size > 100 * 1024) g["small  100 KB – 1 MB"].push(obj);
      else g["tiny  < 100 KB"].push(obj);
    });
    return buckets.filter(b => g[b].length).map(b => ({ label: b, objects: g[b] }));
  }

  if (groupBy === "type") {
    const buckets = ["images", "video", "documents", "archives", "other"];
    const g = {}; buckets.forEach(b => { g[b] = []; });
    objects.forEach(obj => {
      if (obj.media_type === "image") g["images"].push(obj);
      else if (obj.media_type === "video") g["video"].push(obj);
      else if (obj.media_type === "text" || obj.media_type === "pdf") g["documents"].push(obj);
      else if (obj.media_type === "archive") g["archives"].push(obj);
      else g["other"].push(obj);
    });
    return buckets.filter(b => g[b].length).map(b => ({ label: b, objects: g[b] }));
  }

  return [{ label: null, objects }];
}

// ── File type helpers ──
function fileTypeIcon(key) {
  const ext = key.toLowerCase().split('.').pop();
  const map = {
    txt: '📝', log: '📝',
    json: '{ }', yaml: '{ }', yml: '{ }', toml: '{ }', ini: '{ }', cfg: '{ }', conf: '{ }',
    md: '#',
    html: '< >', htm: '< >', xml: '< >',
    py: '🐍',
    sh: '$', env: '$',
    csv: '⊞',
    pdf: 'PDF',
    zip: '🗜', tar: '🗜', gz: '🗜', tgz: '🗜', rar: '🗜',
    sql: 'DB',
    js: '{ }',
  };
  return map[ext] || '📄';
}

function fileTypeBadge(key) {
  const ext = key.toLowerCase().split('.').pop().toUpperCase();
  return `<span class="file-type-pill">${esc(ext)}</span>`;
}

// ── Rendering ──
function renderContent(folders, objects) {
  if (currentView === "grid") renderGrid(folders, objects);
  else renderList(folders, objects);
}

function buildCardHtml(obj) {
  const fname = obj.key.split("/").pop();
  if (obj.browsable) {
    const src = `/api/object?bucket=${enc(currentBucket)}&key=${enc(obj.key)}&provider=${enc(currentProvider)}`;
    const sel = selectedKeys.has(obj.key) ? "selected" : "";
    if (obj.media_type === "video") {
      return `<div class="card ${sel}" data-key="${esc(obj.key)}" onclick="handleCardClick(event, '${esc(obj.key)}')">
        <video src="${src}" muted preload="metadata"></video>
        <div class="card-checkbox" onclick="event.stopPropagation(); toggleSelect('${esc(obj.key)}')">${selectedKeys.has(obj.key) ? "✓" : ""}</div>
        <div class="card-overlay">🎬 ${esc(fname)}</div>
        <button class="card-share" onclick="event.stopPropagation(); openShareModal('${esc(obj.key)}')">share</button>
        <button class="card-copy" onclick="event.stopPropagation(); copyS3URI('${esc(obj.key)}')">s3://</button>
      </div>`;
    } else {
      return `<div class="card ${sel}" data-key="${esc(obj.key)}" onclick="handleCardClick(event, '${esc(obj.key)}')">
        <img src="${src}" loading="lazy" alt="${esc(fname)}">
        <div class="card-checkbox" onclick="event.stopPropagation(); toggleSelect('${esc(obj.key)}')">${selectedKeys.has(obj.key) ? "✓" : ""}</div>
        <div class="card-overlay">${esc(fname)}</div>
        <button class="card-share" onclick="event.stopPropagation(); openShareModal('${esc(obj.key)}')">share</button>
        <button class="card-copy" onclick="event.stopPropagation(); copyS3URI('${esc(obj.key)}')">s3://</button>
        <button class="card-info" onclick="event.stopPropagation(); openExifPanel('${esc(obj.key)}')">i</button>
      </div>`;
    }
  } else {
    const icon = fileTypeIcon(obj.key);
    return `<div class="card-file" onclick="openFilePreview('${esc(obj.key)}')" title="${esc(fname)}">
      <div class="file-icon">${esc(icon)}</div>
      <div class="file-name">${esc(fname)}</div>
      <button class="card-copy" style="opacity:1;position:absolute;bottom:6px;right:6px;font-size:10px" onclick="event.stopPropagation(); copyS3URI('${esc(obj.key)}')">s3://</button>
    </div>`;
  }
}

function renderGrid(folders, objects) {
  if (!folders.length && !objects.length) {
    $content.innerHTML = `<div class="empty-state">
      <div class="es-icon">📭</div>
      <div class="es-title">This location is empty</div>
      <div class="es-sub">Drag & drop files here or click Upload</div>
    </div>`;
    return;
  }

  sortObjects(objects);

  // Build folder cards (always at top, never grouped)
  let foldersHtml = "";
  folders.forEach(f => {
    const name = f.replace(currentPrefix, "").replace(/\/$/, "");
    foldersHtml += `<div class="card-folder" onclick="navigateTo('${esc(f)}')">
      <div class="folder-icon">📁</div>
      <div class="folder-name">${esc(name)}</div>
    </div>`;
  });

  let html = "";
  if (groupBy === "none") {
    html = '<div class="grid">' + foldersHtml;
    objects.forEach(obj => { html += buildCardHtml(obj); });
    html += "</div>";
  } else {
    if (foldersHtml) html += '<div class="grid">' + foldersHtml + "</div>";
    groupObjects(objects).forEach(group => {
      html += `<div class="group-section">
        <div class="group-label">${esc(group.label)}<span class="group-count">${group.objects.length}</span></div>
        <div class="grid">`;
      group.objects.forEach(obj => { html += buildCardHtml(obj); });
      html += "</div></div>";
    });
  }

  $content.innerHTML = html;
}

function renderList(folders, objects) {
  sortObjects(objects);
  let html = '<div class="list">';

  folders.forEach(f => {
    const name = f.replace(currentPrefix, "").replace(/\/$/, "");
    html += `<div class="list-row" onclick="navigateTo('${esc(f)}')">
      <span style="font-size:20px">📁</span>
      <span class="name">${esc(name)}/</span>
      <span class="meta">—</span>
      <span class="meta">—</span>
      <span></span>
      <span></span>
    </div>`;
  });

  objects.forEach(obj => {
    const fname = obj.key.split("/").pop();
    const isMedia = obj.media_type === "image" || obj.media_type === "video";
    const thumb = isMedia
      ? `<img class="thumb" src="/api/object?bucket=${enc(currentBucket)}&key=${enc(obj.key)}&provider=${enc(currentProvider)}" loading="lazy">`
      : `<span class="list-file-icon">${esc(fileTypeIcon(obj.key))}</span>`;
    html += `<div class="list-row" onclick="handleCardClick(event, '${esc(obj.key)}')">
      ${thumb}
      <span class="name">${esc(fname)}</span>
      <span class="meta">${formatSize(obj.size)}</span>
      <span class="meta">${new Date(obj.last_modified).toLocaleDateString()}</span>
      ${fileTypeBadge(obj.key)}
      <div style="display:flex;gap:4px">
        <button class="card-share" style="opacity:1;position:static" onclick="event.stopPropagation(); openShareModal('${esc(obj.key)}')">share</button>
        <button class="card-copy" style="opacity:1;position:static" onclick="event.stopPropagation(); copyS3URI('${esc(obj.key)}')">s3://</button>
      </div>
    </div>`;
  });

  html += "</div>";
  $content.innerHTML = html;
}

function showLoading() {
  let html = '<div class="loading-grid">';
  for (let i = 0; i < 20; i++) html += '<div class="skeleton"></div>';
  html += "</div>";
  $content.innerHTML = html;
}

// ── Navigation ──
function navigateTo(prefix) {
  currentPrefix = prefix;
  selectedKeys.clear();
  loadObjects();
}

function updateBreadcrumb() {
  const parts = currentPrefix.split("/").filter(Boolean);
  let html = `<span class="path-segment" onclick="navigateTo('')">${esc(currentBucket)}</span>`;
  let cumulative = "";
  parts.forEach(p => {
    cumulative += p + "/";
    const target = cumulative;
    html += `<span class="path-separator">/</span>
      <span class="path-segment" onclick="navigateTo('${esc(target)}')">${esc(p)}</span>`;
  });
  $breadcrumb.innerHTML = html;
}

function updateCount(folders, total, media) {
  $count.textContent = `${folders} folders · ${media} media · ${total} total`;
}

// ── View toggle ──
function setView(v) {
  currentView = v;
  document.querySelectorAll(".view-toggle button").forEach(b => {
    b.classList.toggle("active", b.dataset.view === v);
  });
  $sortControls.style.display = v === "list" ? "flex" : "none";
  $groupControls.style.display = v === "grid" ? "flex" : "none";
  renderContent(currentFolders, getFilteredObjects());
}

// ── Selection ──
function toggleSelect(key) {
  if (selectedKeys.has(key)) selectedKeys.delete(key);
  else selectedKeys.add(key);
  const card = document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  if (card) {
    card.classList.toggle("selected", selectedKeys.has(key));
    const cb = card.querySelector(".card-checkbox");
    if (cb) cb.textContent = selectedKeys.has(key) ? "✓" : "";
  }
  updateSelectionBtns();
}

function updateSelectionBtns() {
  const n = selectedKeys.size;
  $deleteBtn.style.display = n ? "" : "none";
  $downloadBtn.style.display = n ? "" : "none";
  if (n) $deleteBtn.textContent = `🗑 Delete (${n})`;
  if (n) $downloadBtn.textContent = `⬇ Download (${n})`;
}

function handleCardClick(event, key) {
  const obj = currentObjects.find(o => o.key === key);
  if (!obj || !obj.browsable) return;
  if (obj.media_type === "image" || obj.media_type === "video") {
    const mediaObjects = browsableObjects.filter(o => o.media_type === "image" || o.media_type === "video");
    const idx = mediaObjects.findIndex(o => o.key === key);
    openLightbox(idx);
  } else {
    openFilePreview(key);
  }
}

// ── Lightbox ──
function openLightbox(index) {
  const mediaObjects = browsableObjects.filter(o => o.media_type === "image" || o.media_type === "video");
  if (index < 0 || index >= mediaObjects.length) return;
  lightboxIndex = index;
  const obj = mediaObjects[index];
  const src = `/api/object?bucket=${enc(currentBucket)}&key=${enc(obj.key)}&provider=${enc(currentProvider)}`;
  const fname = obj.key.split("/").pop();

  if (obj.media_type === "video") {
    $lightboxContent.innerHTML = `<video src="${src}" controls autoplay style="max-width:90vw;max-height:85vh;border-radius:12px"></video>`;
  } else {
    $lightboxContent.innerHTML = `<img src="${src}" alt="${esc(fname)}">`;
  }
  $lightboxInfo.textContent = `${fname}  ·  ${formatSize(obj.size)}  ·  ${index + 1} / ${mediaObjects.length}`;
  const $infoBtn = document.getElementById("lightboxInfoBtn");
  if ($infoBtn) $infoBtn.onclick = () => openExifPanel(obj.key);
  $lightbox.classList.add("open");
  document.body.style.overflow = "hidden";
}

function closeLightbox() {
  $lightbox.classList.remove("open");
  document.body.style.overflow = "";
  $lightboxContent.innerHTML = "";
}

function navLightbox(dir) {
  const mediaObjects = browsableObjects.filter(o => o.media_type === "image" || o.media_type === "video");
  const next = lightboxIndex + dir;
  if (next >= 0 && next < mediaObjects.length) openLightbox(next);
}

// ── Upload ──
async function uploadFiles(fileList) {
  if (!currentBucket) return;

  const toast = $uploadToast;
  const total = fileList.length;
  let done = 0;

  toast.classList.add("show");
  $uploadFill.style.width = "0%";
  $uploadStatus.textContent = `0 / ${total}`;

  const fd = new FormData();
  fd.append("bucket", currentBucket);
  fd.append("prefix", currentPrefix);
  fd.append("provider", currentProvider);
  for (const f of fileList) fd.append("files", f);

  try {
    const resp = await fetch("/api/upload", { method: "POST", body: fd });
    const data = await resp.json();

    $uploadFill.style.width = "100%";
    const ok = data.uploaded?.length || 0;
    const errs = data.errors?.length || 0;
    $uploadStatus.textContent = `${ok} uploaded` + (errs ? `, ${errs} failed` : "");

    if (ok) showToast(`${ok} file${ok > 1 ? "s" : ""} uploaded`, "success");
    if (errs) showToast(`${errs} file${errs > 1 ? "s" : ""} failed`, "error");

    setTimeout(() => toast.classList.remove("show"), 3000);
    $fileInput.value = "";
    loadObjects();
  } catch (err) {
    showToast("Upload failed: " + err.message, "error");
    toast.classList.remove("show");
  }
}

// ── Bulk download ──
async function downloadSelected() {
  if (!selectedKeys.size) return;
  const keys = [...selectedKeys];
  const count = keys.length;

  showToast(`preparing ${count} file${count > 1 ? "s" : ""}...`, "success");

  try {
    const resp = await fetch("/api/download-zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bucket: currentBucket, keys, provider: currentProvider }),
    });

    if (!resp.ok) throw new Error("download failed");

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `bucketlens-${currentBucket}.zip`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`${count} file${count > 1 ? "s" : ""} downloaded`, "success");
  } catch (err) {
    showToast("download failed: " + err.message, "error");
  }
}

// ── Delete 2-step flow ──
function deleteSelected() {
  if (!selectedKeys.size) return;
  const keys = [...selectedKeys];
  const count = keys.length;
  document.getElementById("deleteWarningMsg").textContent =
    `You are about to permanently delete ${count} file${count > 1 ? "s" : ""} from ${currentBucket}`;
  document.getElementById("deleteWarningList").innerHTML = keys.map(k => `<li>${esc(k)}</li>`).join("");
  document.getElementById("deleteWarningModal").classList.add("open");
}

function closeDeleteWarning() {
  document.getElementById("deleteWarningModal").classList.remove("open");
}

function openDeleteConfirmView() {
  closeDeleteWarning();
  const keys = [...selectedKeys];
  $content.innerHTML = `
    <div class="delete-confirm-view">
      <h2>Confirm deletion</h2>
      <div class="dc-sub">${keys.length} file${keys.length > 1 ? "s" : ""} will be permanently removed from <strong>${esc(currentBucket)}</strong></div>
      <div class="delete-warning-banner">⚠ This action cannot be undone. Deleted objects cannot be recovered from S3.</div>
      <ul class="delete-file-list">${keys.map(k => `<li>${esc(k)}</li>`).join("")}</ul>
      <div class="confirm-input-wrap">
        <label class="confirm-input-label" for="bucketConfirmInput">
          Type the bucket name to confirm: <strong style="color:var(--text-primary)">${esc(currentBucket)}</strong>
        </label>
        <input class="confirm-input" id="bucketConfirmInput" type="text"
          placeholder="${esc(currentBucket)}" autocomplete="off" oninput="onConfirmInput()">
      </div>
      <div class="delete-actions">
        <button class="btn-delete-confirm" id="confirmDeleteBtn" disabled onclick="executeDelete()">Confirm Delete</button>
        <button class="btn" onclick="loadObjects()">Go back</button>
      </div>
    </div>`;
}

function onConfirmInput() {
  const input = document.getElementById("bucketConfirmInput");
  const btn = document.getElementById("confirmDeleteBtn");
  const matched = input.value === currentBucket;
  input.classList.toggle("matched", matched);
  btn.disabled = !matched;
}

async function executeDelete() {
  const keys = [...selectedKeys];
  $content.innerHTML = `
    <div class="delete-confirm-view">
      <h2 id="deleteProgressTitle">Deleting…</h2>
      <div class="dc-sub">Deleting ${keys.length} file${keys.length > 1 ? "s" : ""} from ${esc(currentBucket)}</div>
      <div class="delete-progress">
        ${keys.map((k, i) => `
          <div class="progress-item" id="pi-${i}">
            <span class="pi-pending"></span>
            <span class="pi-key">${esc(k)}</span>
          </div>`).join("")}
      </div>
    </div>`;

  let deletedCount = 0;
  for (let i = 0; i < keys.length; i++) {
    const key = keys[i];
    const el = document.getElementById("pi-" + i);
    el.querySelector("span").className = "pi-deleting";
    try {
      const resp = await fetch("/api/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bucket: currentBucket, key, provider: currentProvider }),
      });
      const data = await resp.json();
      if (data.deleted) {
        el.querySelector("span").className = "pi-done";
        deletedCount++;
      } else {
        el.querySelector("span").className = "pi-error";
        el.querySelector(".pi-key").textContent += ` — ${data.error || "failed"}`;
      }
    } catch (err) {
      el.querySelector("span").className = "pi-error";
      el.querySelector(".pi-key").textContent += ` — ${err.message}`;
    }
  }

  const title = document.getElementById("deleteProgressTitle");
  title.textContent = `${deletedCount} of ${keys.length} deleted`;
  title.style.color = deletedCount === keys.length ? "var(--success)" : "var(--warning)";

  selectedKeys.clear();
  updateSelectionBtns();
  showToast(`${deletedCount} file${deletedCount !== 1 ? "s" : ""} deleted`, "success");
  setTimeout(() => loadObjects(), 3000);
}

// ── Provider setup data ──
const PROVIDER_SETUP = {
  aws: {
    title: "AWS — Configure credentials",
    commands: [
      "pip install awscli",
      "aws configure",
      "# When prompted, enter:\n# Access Key ID:     {YOUR_ACCESS_KEY_ID}\n# Secret Access Key: {YOUR_SECRET_ACCESS_KEY}\n# Default region:    {YOUR_REGION}\n# Output format:     json"
    ]
  },
  azure: {
    title: "Azure — Configure credentials",
    commands: [
      "pip install azure-cli",
      "az login",
      "az account set --subscription {YOUR_SUBSCRIPTION_ID}"
    ]
  },
  gcp: {
    title: "GCP — Configure credentials",
    commands: [
      "pip install google-cloud-sdk",
      "gcloud auth application-default login",
      "gcloud config set project {YOUR_PROJECT_ID}"
    ]
  }
};

// ── Provider modal ──
function initProvider() {
  const stored = localStorage.getItem("bl_provider");
  if (stored) {
    currentProvider = stored;
    updateProviderPill();
    loadBuckets();
  } else {
    openProviderModal();
  }
}

function openProviderModal() {
  $providerModal.classList.add("open");
  $credStatus.style.display = "none";
  $credStatus.className = "cred-status";
  $credActions.innerHTML = "";
  $credActions.style.display = "none";
  document.querySelectorAll(".provider-btn").forEach(b => b.classList.remove("active"));
}

function selectProvider(name) {
  currentProvider = name;
  document.querySelectorAll(".provider-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("btn-" + name).classList.add("active");
  checkHealth();
}

async function checkHealth() {
  $credStatus.className = "cred-status cred-checking";
  $credStatus.textContent = "Checking credentials…";
  $credStatus.style.display = "block";
  $credActions.innerHTML = "";
  $credActions.style.display = "none";

  try {
    const resp = await fetch(`/api/health?provider=${enc(currentProvider)}`);
    const data = await resp.json();
    if (data.ok) {
      $credStatus.className = "cred-status cred-ok";
      $credStatus.textContent = "✓ Credentials detected";
      $credActions.innerHTML = `<button class="btn btn-primary" onclick="closeProviderModal()">Continue →</button>`;
    } else {
      $credStatus.className = "cred-status cred-fail";
      $credStatus.textContent = "✗ No credentials found";
      $credActions.innerHTML = `
        <button class="btn" onclick="closeProviderModal()">Confirm anyway</button>
        <button class="btn btn-primary" onclick="openSetupModal()">Show me how</button>`;
    }
  } catch {
    $credStatus.className = "cred-status cred-fail";
    $credStatus.textContent = "✗ Could not reach backend";
    $credActions.innerHTML = `<button class="btn" onclick="closeProviderModal()">Continue anyway</button>`;
  }
  $credActions.style.display = "flex";
}

function closeProviderModal() {
  localStorage.setItem("bl_provider", currentProvider);
  $providerModal.classList.remove("open");
  updateProviderPill();
  loadBuckets();
}

function switchProvider() {
  fetch("/api/reset-provider", { method: "POST" });
  localStorage.removeItem("bl_provider");
  currentProvider = "";
  $bucket.innerHTML = '<option value="">— select bucket —</option>';
  currentBucket = "";
  currentPrefix = "";
  currentObjects = [];
  browsableObjects = [];
  currentFolders = [];
  selectedKeys.clear();
  $content.innerHTML = `<div class="empty-state">
    <div class="es-icon">☁️</div>
    <div class="es-title">Welcome to BucketLens</div>
    <div class="es-sub">images, video, documents, code — everything in your bucket</div>
  </div>`;
  openProviderModal();
}

function updateProviderPill() {
  if (currentProvider) {
    $providerPill.textContent = currentProvider.toUpperCase();
    $providerPill.style.display = "inline-block";
    $switchProviderBtn.style.display = "inline-block";
  } else {
    $providerPill.style.display = "none";
    $switchProviderBtn.style.display = "none";
  }
}

// ── Setup sub-modal ──
function openSetupModal() {
  const setup = PROVIDER_SETUP[currentProvider];
  if (!setup) return;
  document.getElementById("setupTitle").textContent = setup.title;
  const cmds = setup.commands.map(cmd => {
    const display = cmd.replace(/\{[^}]+\}/g, m => `<span class="ph">${esc(m)}</span>`);
    return `<div class="cmd-block">
      <code>${display}</code>
      <button class="copy-btn" data-plain="${esc(cmd)}" onclick="copyCmd(this)">Copy</button>
    </div>`;
  }).join("");
  document.getElementById("setupCommands").innerHTML = cmds;
  $setupModal.classList.add("open");
}

function closeSetupModal() {
  $setupModal.classList.remove("open");
}

async function recheckHealth() {
  closeSetupModal();
  await checkHealth();
}

function copyCmd(btn) {
  const text = btn.dataset.plain;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "Copied!";
    setTimeout(() => btn.textContent = "Copy", 1500);
  });
}

// ── Share / presign modal ──
let shareKey = "";
let shareExpiry = 3600;

function openShareModal(key) {
  shareKey = key;
  shareExpiry = 3600;
  const fname = key.split("/").pop();
  document.getElementById("shareModalTitle").textContent = `share link for ${fname}`;
  document.getElementById("presignedUrl").value = "";
  document.getElementById("presignExpiry").textContent = "";
  document.querySelectorAll(".expiry-btn").forEach((b, i) => b.classList.toggle("active", i === 0));
  document.getElementById("shareModal").classList.add("open");
  fetchPresignedUrl();
}

async function fetchPresignedUrl() {
  document.getElementById("presignedUrl").value = "generating…";
  try {
    const resp = await fetch(`/api/presign?bucket=${enc(currentBucket)}&key=${enc(shareKey)}&expires=${shareExpiry}&provider=${enc(currentProvider)}`);
    const data = await resp.json();
    if (data.error) { document.getElementById("presignedUrl").value = "error: " + data.error; return; }
    document.getElementById("presignedUrl").value = data.url;
    document.getElementById("presignExpiry").textContent =
      `expires ${new Date(data.expires_at).toLocaleString()}`;
  } catch (err) {
    document.getElementById("presignedUrl").value = "error: " + err.message;
  }
}

function setShareExpiry(secs) {
  shareExpiry = secs;
  const btns = document.querySelectorAll(".expiry-btn");
  const secMap = [3600, 28800, 86400, 604800];
  btns.forEach((b, i) => b.classList.toggle("active", secMap[i] === secs));
  fetchPresignedUrl();
}

function copyPresignedUrl() {
  const val = document.getElementById("presignedUrl").value;
  if (!val || val.startsWith("generating") || val.startsWith("error")) return;
  const btn = document.querySelector("#shareModal .btn-primary");
  const flash = () => {
    const orig = btn.textContent;
    btn.textContent = "copied!";
    setTimeout(() => { btn.textContent = orig; }, 2000);
  };
  navigator.clipboard.writeText(val).then(flash).catch(() => {
    const el = document.createElement("textarea");
    el.value = val; document.body.appendChild(el);
    el.select(); document.execCommand("copy"); document.body.removeChild(el);
    flash();
  });
}

function closeShareModal() {
  document.getElementById("shareModal").classList.remove("open");
}

// ── Shortcuts modal ──
function openShortcutsModal() {
  document.getElementById("shortcutsModal").classList.add("open");
}
function closeShortcutsModal() {
  document.getElementById("shortcutsModal").classList.remove("open");
}

// ── Copy S3 URI ──
function copyS3URI(key) {
  let uri;
  if (currentProvider === "azure") uri = `https://${currentBucket}.blob.core.windows.net/${key}`;
  else if (currentProvider === "gcp") uri = `gs://${currentBucket}/${key}`;
  else uri = `s3://${currentBucket}/${key}`;
  navigator.clipboard.writeText(uri).then(() => {
    showToast(`copied: ${uri}`, "success");
  }).catch(() => {
    const el = document.createElement("textarea");
    el.value = uri;
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
    showToast(`copied: ${uri}`, "success");
  });
}

// ── Bucket info modal ──
function openBucketInfoModal(name) {
  document.getElementById("bucketInfoName").textContent = name;
  document.getElementById("bucketInfoDontShowName").textContent = name;
  document.getElementById("bucketInfoDontShow").checked = false;
  document.getElementById("bucketInfoModal").classList.add("open");
}

function confirmBucketInfo() {
  if (document.getElementById("bucketInfoDontShow").checked) {
    localStorage.setItem("bl_seen_bucket_" + currentBucket, "1");
  }
  document.getElementById("bucketInfoModal").classList.remove("open");
  loadObjects();
}

function cancelBucketInfo() {
  document.getElementById("bucketInfoModal").classList.remove("open");
  $bucket.value = "";
  currentBucket = "";
  $uploadBtn.style.display = "none";
}

// ── File preview modal ──
function openFilePreview(key) {
  const fname = key.split("/").pop();
  const ext = fname.toLowerCase().split('.').pop();
  const dlUrl = `/api/object?bucket=${enc(currentBucket)}&key=${enc(key)}&download=1&provider=${enc(currentProvider)}`;
  const s3uri = `s3://${currentBucket}/${key}`;

  const modal = document.getElementById("filePreviewModal");
  document.getElementById("fpFilename").textContent = fname;
  document.getElementById("fpSize").textContent = "";
  document.getElementById("fpDownloadBtn").href = dlUrl;
  document.getElementById("fpCopyBtn").onclick = () => copyS3URI(key);
  document.getElementById("fpBody").innerHTML = `<div class="fp-loading">loading…</div>`;
  modal.classList.add("open");
  document.body.style.overflow = "hidden";

  fetch(`/api/preview?bucket=${enc(currentBucket)}&key=${enc(key)}&provider=${enc(currentProvider)}`)
    .then(async r => {
      const data = await r.json();
      if (!r.ok) {
        if (r.status === 413) {
          document.getElementById("fpBody").innerHTML =
            `<div class="fp-error">file too large to preview (${formatSize(data.size)})<br>
            <span class="fp-note">// preview limit is 1MB</span><br><br>
            <a href="${dlUrl}" class="fp-dl-link">Download file instead →</a></div>`;
        } else {
          document.getElementById("fpBody").innerHTML =
            `<div class="fp-error">binary file — cannot preview in browser<br><br>
            <a href="${dlUrl}" class="fp-dl-link">Download file instead →</a></div>`;
        }
        return;
      }

      document.getElementById("fpSize").textContent = formatSize(data.size);

      if (ext === "csv") {
        document.getElementById("fpBody").innerHTML = renderCsvTable(data.content);
      } else {
        document.getElementById("fpBody").innerHTML =
          `<pre class="fp-code"><code>${esc(data.content)}</code></pre>`;
      }
    })
    .catch(err => {
      document.getElementById("fpBody").innerHTML =
        `<div class="fp-error">failed to load: ${esc(err.message)}</div>`;
    });
}

function renderCsvTable(csv) {
  const rows = csv.trim().split("\n").map(r => r.split(","));
  if (!rows.length) return "<p>empty file</p>";
  const header = rows[0];
  const body = rows.slice(1);
  const th = header.map(c => `<th>${esc(c.trim())}</th>`).join("");
  const tr = body.map((row, i) =>
    `<tr class="${i % 2 === 0 ? "fp-row-even" : "fp-row-odd"}">${
      row.map(c => `<td>${esc(c.trim())}</td>`).join("")
    }</tr>`
  ).join("");
  return `<div class="fp-table-wrap"><table class="fp-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

function closeFilePreview() {
  document.getElementById("filePreviewModal").classList.remove("open");
  document.body.style.overflow = "";
  document.getElementById("fpBody").innerHTML = "";
}

// ── Helpers ──
function enc(s) { return encodeURIComponent(s); }
function esc(s) { return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
function formatSize(bytes) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}
function showToast(msg, type = "success") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  document.getElementById("toastContainer").appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── EXIF panel ──
function openExifPanel(key) {
  exifCurrentKey = key;
  exifPanelOpen = true;
  const panel = document.getElementById("exifPanel");
  const backdrop = document.getElementById("exifBackdrop");
  panel.classList.add("open");
  backdrop.style.display = "block";
  document.getElementById("exifContent").innerHTML = '<div class="exif-loading">fetching metadata...</div>';
  fetch(`/api/exif?bucket=${enc(currentBucket)}&key=${enc(key)}&provider=${enc(currentProvider)}`)
    .then(r => r.json())
    .then(renderExifPanel)
    .catch(() => {
      document.getElementById("exifContent").innerHTML = '<div class="exif-error">failed to load metadata</div>';
    });
}

function closeExifPanel() {
  exifPanelOpen = false;
  document.getElementById("exifPanel").classList.remove("open");
  document.getElementById("exifBackdrop").style.display = "none";
}

function exifSection(title, rows) {
  if (!rows.length) return "";
  const rowsHtml = rows.map(([label, val]) =>
    `<div class="exif-row">
      <span class="exif-label">${esc(String(label))}</span>
      <span class="exif-value">${esc(String(val))}</span>
    </div>`
  ).join("");
  return `<div class="exif-section">
    <div class="exif-section-title">${esc(title)}</div>
    ${rowsHtml}
  </div>`;
}

function renderExifPanel(data) {
  if (data.error) {
    document.getElementById("exifContent").innerHTML = `<div class="exif-error">${esc(data.error)}</div>`;
    return;
  }
  const fname = data.filename;
  const size = formatSize(data.file_size);
  const dims = `${data.width} × ${data.height}`;
  const modified = data.last_modified ? new Date(data.last_modified).toLocaleString() : "—";
  const src = `/api/object?bucket=${enc(currentBucket)}&key=${enc(data.key)}&provider=${enc(currentProvider)}`;

  let html = `<div class="exif-thumb-wrap"><img src="${src}" class="exif-thumb" alt="${esc(fname)}"></div>`;

  html += exifSection("file", [
    ["filename", fname],
    ["dimensions", dims],
    ["file size", size],
    ["format", data.format],
    ["color mode", data.mode],
    ["modified", modified],
    ["provider", data.provider],
  ]);

  const camera = [];
  if (data.exif.Make) camera.push(["make", data.exif.Make]);
  if (data.exif.Model) camera.push(["model", data.exif.Model]);
  if (data.exif.LensMake) camera.push(["lens make", data.exif.LensMake]);
  if (data.exif.LensModel) camera.push(["lens", data.exif.LensModel]);
  if (camera.length) html += exifSection("camera", camera);

  const exposure = [];
  if (data.exif.ExposureTime) exposure.push(["shutter", data.exif.ExposureTime]);
  if (data.exif.FNumber) exposure.push(["aperture", data.exif.FNumber]);
  if (data.exif.ISOSpeedRatings) exposure.push(["iso", data.exif.ISOSpeedRatings]);
  if (data.exif.FocalLength) exposure.push(["focal length", data.exif.FocalLength]);
  if (data.exif.FocalLengthIn35mmFilm) exposure.push(["35mm equiv", `${data.exif.FocalLengthIn35mmFilm}mm`]);
  if (data.exif.ExposureMode !== undefined) exposure.push(["exposure mode", data.exif.ExposureMode]);
  if (data.exif.WhiteBalance !== undefined) exposure.push(["white balance", data.exif.WhiteBalance]);
  if (data.exif.Flash !== undefined) exposure.push(["flash", data.exif.Flash]);
  if (exposure.length) html += exifSection("exposure", exposure);

  const dates = [];
  if (data.exif.DateTimeOriginal) dates.push(["taken", data.exif.DateTimeOriginal]);
  if (data.exif.DateTime) dates.push(["modified", data.exif.DateTime]);
  if (dates.length) html += exifSection("dates", dates);

  if (data.gps) {
    html += exifSection("location", [
      ["latitude", data.gps.lat],
      ["longitude", data.gps.lon],
    ]);
    html += `<a href="${data.gps.maps_url}" target="_blank" rel="noopener" class="exif-maps-link">open in google maps →</a>`;
  }

  if (!Object.keys(data.exif).length && !data.gps) {
    html += `<div class="exif-no-data">// no EXIF data in this image<br>// common for screenshots and web images</div>`;
  }

  html += `<div class="exif-actions">
    <button class="btn btn-sm" onclick="copyS3URI('${esc(data.key)}')">copy uri</button>
    <button class="btn btn-sm" onclick="openShareModal('${esc(data.key)}')">share</button>
    <a class="btn btn-sm" href="/api/object?bucket=${enc(currentBucket)}&key=${enc(data.key)}&provider=${enc(currentProvider)}&download=1" download="${esc(fname)}">download</a>
  </div>`;

  document.getElementById("exifContent").innerHTML = html;
}

// ── Thumbnail cache ──
async function loadCacheStats() {
  try {
    const resp = await fetch('/api/cache/stats');
    const data = await resp.json();
    const el = document.getElementById('cacheStats');
    if (!el) return;
    if (!data.pillow_available) {
      el.textContent = 'thumbnail cache disabled\ninstall Pillow to enable:\npip install Pillow';
      return;
    }
    el.textContent =
      `cached thumbnails  ${data.cached_thumbs}\n` +
      `cache size         ${data.total_size_human}\n` +
      `cache limit        500 MB\n` +
      `cache dir          ${data.cache_dir}`;
  } catch { /* silently fail */ }
}

async function clearThumbnailCache() {
  if (!confirm('Clear all cached thumbnails?')) return;
  try {
    const resp = await fetch('/api/cache/clear', {method: 'DELETE'});
    const data = await resp.json();
    showToast(data.message || 'cache cleared', 'success');
    loadCacheStats();
  } catch { showToast('failed to clear cache', 'error'); }
}
