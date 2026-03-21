// Shared carousel builder used across pages (stream, profile, entry detail)

export function buildCarousel(images, container) {
  if (!container) return;

  if (!images || !images.length) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = `
    <div class="carousel">
      <div class="carousel__track">
        ${images
          .map(
            (img) => `
          <div class="carousel__slide">
            <img src="${img.src}" alt="${img.alt}" />
          </div>`
          )
          .join("")}
      </div>
      ${
        images.length > 1
          ? `
        <button class="carousel__btn carousel__btn--prev" type="button" aria-label="Previous">&#8249;</button>
        <button class="carousel__btn carousel__btn--next" type="button" aria-label="Next">&#8250;</button>
        <div class="carousel__dots">
          ${images
            .map(
              (_, i) =>
                `<button type="button" class="carousel__dot${i === 0 ? " carousel__dot--active" : ""}" data-index="${i}"></button>`
            )
            .join("")}
        </div>`
          : ""
      }
    </div>`;

  if (images.length === 1) return;

  const track = container.querySelector(".carousel__track");
  const dots = Array.from(container.querySelectorAll(".carousel__dot"));
  let current = 0;

  function goTo(index) {
    current = (index + images.length) % images.length;
    if (track) track.style.transform = `translateX(-${current * 100}%)`;
    dots.forEach((d, i) => d.classList.toggle("carousel__dot--active", i === current));
  }

  const prevBtn = container.querySelector(".carousel__btn--prev");
  const nextBtn = container.querySelector(".carousel__btn--next");

  if (prevBtn) prevBtn.addEventListener("click", () => goTo(current - 1));
  if (nextBtn) nextBtn.addEventListener("click", () => goTo(current + 1));
  dots.forEach((d) => d.addEventListener("click", () => goTo(parseInt(d.dataset.index, 10))));
}
