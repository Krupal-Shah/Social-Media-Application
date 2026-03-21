import { marked } from "marked";
import { buildCarousel } from "./ui/carousel.js";
import DOMPurify from "dompurify";

document.addEventListener("DOMContentLoaded", () => {

  // Render markdown
  document.querySelectorAll("[data-markdown]").forEach((el) => {
    try {
      // el.innerHTML = marked.parse(el.getAttribute("data-markdown") || "");
      el.innerHTML = DOMPurify.sanitize(marked.parse(el.getAttribute("data-markdown") || ""));
    } catch {
      el.textContent = el.getAttribute("data-markdown") || "";
    }
  });

  // Render galleries as carousel
  document.querySelectorAll("[data-gallery]").forEach((el) => {
    let parsed;
    try {
      parsed = JSON.parse(el.getAttribute("data-gallery") || "[]");
    } catch {
      parsed = [];
    }

    if (!Array.isArray(parsed)) return;

    const images = parsed
      .filter((img) => img && img.type && img.data)
      .map((img) => ({
        src: `data:${img.type};base64,${img.data}`,
        alt: "Image",
      }));

    buildCarousel(images, el);
  });
});
