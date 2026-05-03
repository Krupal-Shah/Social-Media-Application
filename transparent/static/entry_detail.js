import { marked } from "https://cdn.jsdelivr.net/npm/marked@17.0.3/lib/marked.esm.js";
import DOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.3.3/+esm";

document.addEventListener("DOMContentLoaded", () => {
  // Render markdown
  document.querySelectorAll("[data-markdown]").forEach((el) => {
    try {
      // el.innerHTML = marked.parse(el.getAttribute("data-markdown") || "");
      el.innerHTML = DOMPurify.sanitize(
        marked.parse(el.getAttribute("data-markdown") || ""),
      );
    } catch {
      el.textContent = el.getAttribute("data-markdown") || "";
    }
  });
});
