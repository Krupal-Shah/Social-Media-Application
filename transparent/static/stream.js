import { marked } from "https://cdn.jsdelivr.net/npm/marked@17.0.3/lib/marked.esm.js";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.3.3/+esm";

document.addEventListener("DOMContentLoaded", () => {
  // Keep this near the top so it still works even if later feed logic throws.

  // ── DOM references ────────────────────────────────────────────────────────────
  const modal = document.getElementById("postModal");
  const closeBtn = document.getElementById("closePostModal");
  const textarea = document.getElementById("postContent");
  const imageOption = document.getElementById("imageOption");
  const markdownOption = document.getElementById("markdownOption");
  const imageSection = document.getElementById("imageUploadSection");
  const imageFileInput = document.getElementById("imageFileInput");
  const imageIndicator = document.getElementById("imageIndicator");
  const imagePreviewCarousel = document.getElementById("imagePreviewCarousel");
  const markdownPreview = document.getElementById("markdownPreview");
  const visibilitySelect = document.querySelector(".modal__visibility");
  const visibilityHidden = document.getElementById("visibilityHidden");

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
    if (
      e.key === "Escape" &&
      modal.classList.contains("modal-overlay--visible")
    ) {
      closeModal();
    }
  });

  // ── Image upload (single image only) ────────────────────────────────────────
  let selectedFile = null;

  function refreshImageUI() {
    if (!selectedFile) {
      imageIndicator.style.display = "none";
      imagePreviewCarousel.style.display = "none";
      imagePreviewCarousel.innerHTML = "";
      return;
    }

    imageIndicator.textContent = "1 image selected";
    imageIndicator.className = "modal__image-indicator";
    imageIndicator.style.display = "block";

    imagePreviewCarousel.innerHTML = `<img src="${URL.createObjectURL(selectedFile)}" alt="Preview" style="width: 100%; border-radius: 8px; object-fit: cover;" />`;
    imagePreviewCarousel.style.display = "block";
  }

  function resetImagePicker() {
    selectedFile = null;
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
    const files = Array.from(imageFileInput.files || []);
    if (!files.length) return;
    selectedFile = files[0];
    refreshImageUI();
  });

  // Visibility sync
  visibilitySelect.addEventListener("change", () => {
    visibilityHidden.value = visibilitySelect.value;
  });

  // Render markdown entries in the feed (never let a bad post break the whole page)
  document.querySelectorAll("[data-markdown]").forEach((el) => {
    try {
      // el.innerHTML = marked.parse(el.dataset.markdown || "");
      el.innerHTML = DOMPurify.sanitize(
        marked.parse(el.dataset.markdown || ""),
      );
    } catch {
      // Fall back to plain text if something unexpected is in the dataset.
      el.textContent = el.dataset.markdown || "";
    }
  });

  // Markdown live preview
  function updateMarkdownPreview() {
    const isMarkdown = markdownOption.checked;
    if (isMarkdown && textarea.value.trim()) {
      // markdownPreview.innerHTML = marked.parse(textarea.value);
      markdownPreview.innerHTML = DOMPurify.sanitize(
        marked.parse(textarea.value),
      );

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
