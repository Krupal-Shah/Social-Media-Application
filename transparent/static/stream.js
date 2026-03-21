import { marked } from "marked";
import { buildCarousel } from "./ui/carousel.js";
import DOMPurify from "dompurify";

document.addEventListener("DOMContentLoaded", () => {
// Keep this near the top so it still works even if later feed logic throws.

// ── DOM references ────────────────────────────────────────────────────────────
const modal                 = document.getElementById("postModal");
const closeBtn              = document.getElementById("closePostModal");
const textarea              = document.getElementById("postContent");
const imageOption           = document.getElementById("imageOption");
const markdownOption        = document.getElementById("markdownOption");
const imageSection          = document.getElementById("imageUploadSection");
const imageFileInput        = document.getElementById("imageFileInput");
const imageIndicator        = document.getElementById("imageIndicator");
const imagePreviewCarousel  = document.getElementById("imagePreviewCarousel");
const markdownPreview       = document.getElementById("markdownPreview");
const visibilitySelect      = document.querySelector(".modal__visibility");
const visibilityHidden      = document.getElementById("visibilityHidden");

// ── Modal open / close ────────────────────────────────────────────────────────
function openModal() {
  modal.classList.add("modal-overlay--visible");
  document.body.style.overflow = "hidden";
}

function closeModal() {
  modal.classList.remove("modal-overlay--visible");
  document.body.style.overflow = "";
  // Reset all inputs and previews
  textarea.value = "";
  markdownOption.checked = false;
  markdownPreview.innerHTML = "";
  markdownPreview.style.display = "none";
  if (typeof resetImagePicker === "function") {
    resetImagePicker();
    imageOption.checked = false;
    imageSection.style.display = "none";
  }
}

// Button triggers
const openPostModalBtn = document.getElementById("openPostModal");
if (openPostModalBtn) {
  openPostModalBtn.addEventListener("click", () => openModal());
}

// Close via button, backdrop click, or Escape key
if (closeBtn) closeBtn.addEventListener("click", closeModal);

if (modal) {
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && modal.classList.contains("modal-overlay--visible")) {
    closeModal();
  }
});

// ── Image upload ─────────────────────────────────────────────────────────────
// The following image functions are written by Github Copilot, "How to build an image upload preview with a maximum limit in JavaScript", 2026-02-28
const MAX_IMAGES = 5;
let selectedFiles = [];   // accumulated across multiple picks

function syncFilesToInput() {
  const dt = new DataTransfer();
  selectedFiles.forEach(f => dt.items.add(f));
  imageFileInput.files = dt.files;
}

function refreshImageUI() {
  if (selectedFiles.length === 0) {
    imageIndicator.style.display = "none";
    imagePreviewCarousel.style.display = "none";
    imagePreviewCarousel.innerHTML = "";
    return;
  }
  const atMax = selectedFiles.length === MAX_IMAGES;
  imageIndicator.textContent = `${selectedFiles.length} image${selectedFiles.length > 1 ? "s" : ""} selected${atMax ? " — maximum reached" : ""}`;
  imageIndicator.className = `modal__image-indicator${atMax ? " modal__image-indicator--max" : ""}`;
  imageIndicator.style.display = "block";

  const previews = selectedFiles.map(f => ({ src: URL.createObjectURL(f), alt: f.name }));
  buildCarousel(previews, imagePreviewCarousel);
  imagePreviewCarousel.style.display = "block";
}

function resetImagePicker() {
  selectedFiles = [];
  imageFileInput.value = "";
  imageIndicator.style.display = "none";
  imagePreviewCarousel.style.display = "none";
  imagePreviewCarousel.innerHTML = "";
}

imageOption.addEventListener("change", () => {
  imageSection.style.display = imageOption.checked ? "block" : "none";
  if (!imageOption.checked) resetImagePicker();
});

imageFileInput.addEventListener("change", () => {
  const newFiles = Array.from(imageFileInput.files);
  if (newFiles.length === 0) return;

  // Merge, skipping duplicates by name+size, capped at MAX_IMAGES
  for (const file of newFiles) {
    if (selectedFiles.length >= MAX_IMAGES) break;
    const isDuplicate = selectedFiles.some(f => f.name === file.name && f.size === file.size);
    if (!isDuplicate) selectedFiles.push(file);
  }

  const totalNew = Array.from(imageFileInput.files).length;
  const wouldExceed = selectedFiles.length === MAX_IMAGES && totalNew > (MAX_IMAGES - (selectedFiles.length - newFiles.filter(f =>
    !selectedFiles.some(s => s.name === f.name && s.size === f.size)).length));

  // Show a warning if the user tried to add more than the cap allows
  if (selectedFiles.length === MAX_IMAGES) {
    imageIndicator.textContent = `${MAX_IMAGES} images selected — maximum reached`;
    imageIndicator.className = "modal__image-indicator modal__image-indicator--max";
    imageIndicator.style.display = "block";
  }

  syncFilesToInput();
  refreshImageUI();
});

// Visibility sync
visibilitySelect.addEventListener("change", () => {
  visibilityHidden.value = visibilitySelect.value;
});

function safeJsonParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// Render markdown entries in the feed (never let a bad post break the whole page)
document.querySelectorAll("[data-markdown]").forEach((el) => {
  try {
    // el.innerHTML = marked.parse(el.dataset.markdown || "");
    el.innerHTML = DOMPurify.sanitize(marked.parse(el.dataset.markdown || ""));
  } catch {
    // Fall back to plain text if something unexpected is in the dataset.
    el.textContent = el.dataset.markdown || "";
  }
});

// Render image gallery entries in the feed
document.querySelectorAll("[data-gallery]").forEach((el) => {
  const parsed = safeJsonParse(el.dataset.gallery || "[]");
  if (!Array.isArray(parsed)) return;

  const images = parsed
    .filter((img) => img && img.type && img.data)
    .map((img) => ({
      src: `data:${img.type};base64,${img.data}`,
      alt: "Image",
    }));

  buildCarousel(images, el);
});

// Markdown live preview
function updateMarkdownPreview() {
  const isMarkdown = markdownOption.checked;
  if (isMarkdown && textarea.value.trim()) {
    // markdownPreview.innerHTML = marked.parse(textarea.value);
    markdownPreview.innerHTML = DOMPurify.sanitize(marked.parse(textarea.value));

    markdownPreview.style.display = "block";
  } else {
    markdownPreview.innerHTML = "";
    markdownPreview.style.display = "none";
  }
}

markdownOption.addEventListener("change", updateMarkdownPreview);
textarea.addEventListener("input", () => {
  if (markdownOption.checked) updateMarkdownPreview();
});
});

