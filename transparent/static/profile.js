/* Profile overlay + grid rendering + AJAX edit */
import { marked } from "marked";
import { buildCarousel } from "./ui/carousel.js";
import DOMPurify from "dompurify";

(function () {
  "use strict";
  // Enable navbar dropdown on profile page (profile overrides stream.min.js)

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }

  function parseGallery(galleryStr) {
    if (!galleryStr) return [];
    try {
      return JSON.parse(galleryStr);
    } catch (e) {
      return [];
    }
  }

  // Mirrors _annotate_entry logic from views.py
  function annotateEntry(contentType, content) {
    var ct = contentType || "";
    var hasGallery = ct.indexOf("image/gallery") !== -1;
    var hasImage = ct.indexOf("image/") !== -1;
    var hasText = ct.indexOf("text/") !== -1;
    var isMarkdown = ct.indexOf("text/markdown") !== -1;

    var result = {
      hasGallery: hasGallery,
      hasImage: hasImage && !hasGallery,
      isMarkdown: isMarkdown,
      imageSrc: "",
      galleryJson: "[]",
      text: ""
    };

    if (hasImage && hasText) {
      var data = {};
      try { data = JSON.parse(content); } catch (e) {}
      result.text = data.text || "";
      if (hasGallery) {
        result.galleryJson = JSON.stringify(data.gallery || []);
      } else {
        var imgType = ct.split("/text/")[0];
        result.imageSrc = "data:" + imgType + ";base64," + (data.image || "");
      }
    } else if (hasGallery) {
      result.galleryJson = content;
    } else if (hasImage) {
      result.imageSrc = "data:" + ct + ";base64," + content;
    } else {
      result.text = content;
    }

    return result;
  }

  function hydrateGalleryThumbs() {
    qsa("[data-gallery-thumb]").forEach(function (node) {
      if (node.dataset.hydrated === "1") return;
      var items = parseGallery(node.getAttribute("data-gallery"));
      if (!items.length) return;

      var img = document.createElement("img");
      img.className = "grid-cell__img";
      img.loading = "lazy";
      img.alt = "Gallery";
      img.src = "data:" + items[0].type + ";base64," + items[0].data;
      node.replaceWith(img);
      // leave the badge as-is
    });
  }

  // Determine visibility of view elements by inspecting actual content,
  // not the raw content_type string, so combined types work correctly.
  function setStoreViewMode(containerEl) {
    var gallery = qs(".js-view-gallery", containerEl);
    var image = qs(".js-view-image", containerEl);
    var markdown = qs(".js-view-markdown", containerEl);
    var plain = qs(".js-view-plain", containerEl);

    var galleryData = gallery ? (gallery.getAttribute("data-gallery") || "") : "";
    var imageSrc = image ? (image.getAttribute("src") || "") : "";
    var mdData = markdown ? (markdown.getAttribute("data-markdown") || "") : "";
    var plainText = plain ? (plain.textContent || "").trim() : "";

    if (gallery) gallery.style.display = (galleryData && galleryData.length > 2) ? "grid" : "none";
    if (image) image.style.display = imageSrc.startsWith("data:") ? "block" : "none";
    if (markdown) markdown.style.display = mdData ? "block" : "none";
    if (plain) plain.style.display = (!mdData && plainText) ? "block" : "none";
  }

  /* ============================================================
     Overlay state
  ============================================================ */
  var overlay = qs("#entryOverlay");
  if (!overlay) {
    // Not on profile page.
    return;
  }

  var backdrop = qs("#overlayBackdrop");
  var bodyEl = qs("#overlayBody");
  var footerEl = qs("#overlayFooter");
  var titleEl = qs("#overlayTitle");
  var closeBtn = qs("#overlayCloseBtn");

  var currentId = null;

  function storeRoot(id) {
    return qs("#store-" + id);
  }

  function overlaySet(mode, id) {
    currentId = id;

    var store = storeRoot(id);
    if (!store) return;

    if (mode === "view") {
      var viewBody = qs(".store-view-body", store);
      var viewFooter = qs(".store-view-footer", store);
      bodyEl.innerHTML = viewBody ? viewBody.innerHTML : "";
      footerEl.innerHTML = viewFooter ? viewFooter.innerHTML : "";

      // Show/hide elements while data-markdown is still present on the element
      setStoreViewMode(bodyEl);

      // markdown – render after visibility is set
      qsa(".overlay-content-markdown[data-markdown]", bodyEl).forEach(function (el) {
        var md = el.getAttribute("data-markdown") || "";
        if (md) {
          // el.innerHTML = marked.parse(md);
          el.innerHTML = DOMPurify.sanitize(marked.parse(md));
          el.removeAttribute("data-markdown");
        }
      });

      // gallery
      qsa(".overlay-gallery[data-gallery]", bodyEl).forEach(function (wrap) {
        var items = parseGallery(wrap.getAttribute("data-gallery"));
        var images = items
          .filter(function (item) { return item && item.type && item.data; })
          .map(function (item) {
            return {
              src: "data:" + item.type + ";base64," + item.data,
              alt: "Image",
            };
          });
        buildCarousel(images, wrap);
      });
    }

    if (mode === "edit") {
      var editBody = qs(".store-edit-body", store);
      var editFooter = qs(".store-edit-footer", store);
      bodyEl.innerHTML = editBody ? editBody.innerHTML : "";
      footerEl.innerHTML = editFooter ? editFooter.innerHTML : "";
      attachEditImagePicker();
    }

    titleEl.textContent = getTitleFromStore(store);
    attachFooterListeners();
  }

  function getTitleFromStore(store) {
    var input = qs("input[name='title']", store);
    var val = input ? input.value.trim() : "";
    return val ? val : "Post";
  }

  function openOverlay(id) {
    overlaySet("view", id);
    overlay.classList.add("entry-overlay--open");
    document.body.style.overflow = "hidden";
  }

  function closeOverlay() {
    overlay.classList.remove("entry-overlay--open");
    document.body.style.overflow = "";
    setTimeout(function () {
      bodyEl.innerHTML = "";
      footerEl.innerHTML = "";
      currentId = null;
    }, 360);
  }

  // Image picker for the edit overlay (mirrors stream.js logic)
  function attachEditImagePicker() {
    var toggle = qs(".edit-img-toggle", bodyEl);
    var section = qs(".edit-img-section", bodyEl);
    var fileInput = qs(".edit-img-input", bodyEl);
    var indicator = qs(".edit-img-indicator", bodyEl);
    var preview = qs(".edit-img-preview", bodyEl);
    var uploadLabel = qs(".edit-img-upload-area", bodyEl);
    if (!toggle || !section || !fileInput) return;

    var MAX = 5;
    var selectedFiles = [];

    // Make the label click open the file picker
    if (uploadLabel) {
      uploadLabel.addEventListener("click", function (e) {
        if (e.target !== fileInput) fileInput.click();
      });
    }

    function syncFiles() {
      var dt = new DataTransfer();
      selectedFiles.forEach(function (f) { dt.items.add(f); });
      fileInput.files = dt.files;
    }

    function refreshUI() {
      if (!selectedFiles.length) {
        indicator.style.display = "none";
        preview.style.display = "none";
        preview.innerHTML = "";
        return;
      }
      var atMax = selectedFiles.length === MAX;
      indicator.textContent = selectedFiles.length + " image" + (selectedFiles.length > 1 ? "s" : "") + " selected" + (atMax ? " — maximum reached" : "");
      indicator.style.display = "block";
      preview.innerHTML = selectedFiles.map(function (f) {
        return '<img src="' + URL.createObjectURL(f) + '" style="width:58px;height:58px;object-fit:cover;border-radius:4px">';
      }).join("");
      preview.style.display = "flex";
    }

    toggle.addEventListener("change", function () {
      section.style.display = toggle.checked ? "block" : "none";
      if (!toggle.checked) {
        selectedFiles = [];
        fileInput.value = "";
        refreshUI();
      }
    });

    fileInput.addEventListener("change", function () {
      Array.from(fileInput.files).forEach(function (f) {
        if (selectedFiles.length >= MAX) return;
        var dup = selectedFiles.some(function (s) { return s.name === f.name && s.size === f.size; });
        if (!dup) selectedFiles.push(f);
      });
      syncFiles();
      refreshUI();
    });
  }

  function attachFooterListeners() {    qsa("[data-action]", footerEl).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var action = btn.getAttribute("data-action");
        var id = btn.getAttribute("data-id");
        if (!id) return;

        if (action === "edit") overlaySet("edit", id);
        if (action === "cancelEdit") overlaySet("view", id);
        if (action === "submitEdit") submitEditAjax(id);
      });
    });
  }

  function setVisibilityBadge(cell, visibility) {
    var badge = qs(".grid-cell__vis", cell);
    if (!badge) return;

    badge.textContent = visibility;
    badge.className = "grid-cell__vis grid-cell__vis--" + String(visibility || "").toLowerCase();
  }

  function setOverlayVisibility(bodyRoot, visibility) {
    var badge = qs(".overlay-vis-badge", bodyRoot);
    if (!badge) return;
    badge.textContent = visibility;
    badge.className = "overlay-vis-badge overlay-vis-badge--" + String(visibility || "").toLowerCase();
  }

  function updateGridCellFromJson(data) {
    var cell = qs('.grid-cell[data-id="' + data.id + '"]');
    if (!cell) return;

    var ann = annotateEntry(data.content_type, data.content);

    setVisibilityBadge(cell, data.visibility);

    // Update markdown badge
    var mdBadge = qs(".tile-md-badge", cell);
    if (ann.isMarkdown && !ann.hasImage && !ann.hasGallery) {
      if (!mdBadge) {
        mdBadge = document.createElement("div");
        mdBadge.className = "tile-md-badge";
        mdBadge.textContent = "MD";
        cell.insertBefore(mdBadge, cell.firstChild);
      }
    } else {
      if (mdBadge) mdBadge.remove();
    }

    // Update title and text body on text tiles
    var textTile = qs(".grid-cell__text", cell);
    if (textTile && ann.text) {
      var titleNode = qs(".grid-cell__text-title", textTile);
      if (!titleNode && data.title) {
        titleNode = document.createElement("div");
        titleNode.className = "grid-cell__text-title";
        var icon = qs(".grid-cell__text-icon", textTile);
        if (icon) icon.insertAdjacentElement("afterend", titleNode);
        else textTile.insertAdjacentElement("afterbegin", titleNode);
      }
      if (titleNode) titleNode.textContent = data.title || "";
      var bodyNode = qs(".grid-cell__text-body", textTile);
      if (bodyNode) bodyNode.textContent = ann.text.slice(0, 120);
    }

    // Update single image src
    if (ann.hasImage && ann.imageSrc) {
      var img = qs("img.grid-cell__img", cell);
      if (img) img.src = ann.imageSrc;
    }
  }

  function updateStoreFromJson(data) {
    var store = storeRoot(data.id);
    if (!store) return;

    var ann = annotateEntry(data.content_type, data.content);

    // Edit form fields
    var titleInput = qs("input[name='title']", store);
    if (titleInput) titleInput.value = data.title || "";

    var visSelect = qs("select[name='visibility']", store);
    if (visSelect) visSelect.value = data.visibility || "PUBLIC";

    var contentTextarea = qs("textarea[name='content']", store);
    if (contentTextarea) contentTextarea.value = ann.text;

    var mdCheckbox = qs("input[name='use_markdown']", store);
    if (mdCheckbox) mdCheckbox.checked = ann.isMarkdown;

    // View visibility badge
    var viewVis = qs(".js-view-visibility", store);
    if (viewVis) {
      viewVis.textContent = data.visibility;
      viewVis.className = "overlay-vis-badge js-view-visibility overlay-vis-badge--" + String(data.visibility || "").toLowerCase();
    }

    // Content rendering nodes (store view)
    var galleryNode = qs(".js-view-gallery", store);
    var imgNode = qs(".js-view-image", store);
    var mdNode = qs(".js-view-markdown", store);
    var plainNode = qs(".js-view-plain", store);

    if (galleryNode) galleryNode.setAttribute("data-gallery", ann.galleryJson);
    if (imgNode) imgNode.src = ann.imageSrc || "";
    if (mdNode) mdNode.setAttribute("data-markdown", ann.isMarkdown ? ann.text : "");
    if (plainNode) plainNode.textContent = ann.text;
  }

  function submitEditAjax(id) {
    var form = qs("#edit-form-" + id, bodyEl);
    if (!form) return;

    var fd = new FormData(form);

    fetch(form.action, {
      method: "POST",
      body: fd,
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": getCookie("csrftoken")
      },
      credentials: "same-origin"
    })
      .then(function (res) {
        return res.json().then(function (json) {
          return { ok: res.ok, status: res.status, json: json };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          alert((result.json && result.json.error) ? result.json.error : "Could not save changes.");
          return;
        }

        var data = result.json;
        updateStoreFromJson(data);
        updateGridCellFromJson(data);

        // If overlay is open, re-open view mode to reflect changes.
        overlaySet("view", data.id);
        setOverlayVisibility(bodyEl, data.visibility);
      })
      .catch(function () {
        alert("Could not save changes.");
      });
  }

  /* ============================================================
     Wiring
  ============================================================ */
  hydrateGalleryThumbs();

  // Render any [data-markdown] elements already on the page,
  // but skip elements inside the hidden store (their data-markdown must
  // stay intact so the overlay can read it when a post is opened).
  qsa("[data-markdown]").forEach(function (el) {
    if (el.closest("#entryStore")) return;
    // el.innerHTML = marked.parse(el.getAttribute("data-markdown") || "");
    el.innerHTML = DOMPurify.sanitize(marked.parse(el.getAttribute("data-markdown") || ""));
    el.removeAttribute("data-markdown");
  });

  qsa(".grid-cell").forEach(function (cell) {
    cell.addEventListener("click", function () {
      openOverlay(cell.getAttribute("data-id"));
    });

    cell.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openOverlay(cell.getAttribute("data-id"));
      }
    });
  });

  closeBtn.addEventListener("click", closeOverlay);
  backdrop.addEventListener("click", closeOverlay);

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && overlay.classList.contains("entry-overlay--open")) {
      closeOverlay();
    }
  });
})();
