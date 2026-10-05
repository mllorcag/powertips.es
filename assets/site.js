"use strict";

const normalize = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("es");

async function compatibility() {
  const params = new URLSearchParams(location.search);
  const id = params.get("p") || params.get("page_id");
  const category = params.get("cat");
  const is404 = document.querySelector(".not-found");
  if (!id && !category && !is404) return;
  try {
    const response = await fetch("/compatibility.json");
    if (!response.ok) throw new Error(`Compatibilidad: HTTP ${response.status}`);
    const mapping = await response.json();
    let route = id ? mapping.ids[id] : category ? mapping.categories[category] : null;
    if (!route && is404) {
      const requested = decodeURIComponent(location.pathname).replace(/\/?$/, "/");
      route = mapping.routes.find((path) => decodeURIComponent(path) === requested);
    }
    if (route && location.pathname + location.search !== route) location.replace(route + location.hash);
  } catch (error) {
    console.error("No se pudo consultar la compatibilidad de rutas.", error);
  }
}

async function search() {
  const form = document.getElementById("search-form");
  if (!form) return;
  const input = document.getElementById("search-input");
  const status = document.getElementById("search-status");
  const results = document.getElementById("search-results");
  let index;
  let requestNumber = 0;
  async function run(event) {
    if (event) event.preventDefault();
    const current = ++requestNumber;
    const query = input.value.trim();
    const url = new URL(location.href);
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    history.replaceState(null, "", url);
    results.replaceChildren();
    if (!query) {
      status.textContent = "Escribe un tema para buscar en el archivo.";
      return;
    }
    status.textContent = "Buscando…";
    try {
      if (!index) {
        const response = await fetch("/search-index.json");
        if (!response.ok) throw new Error(`Búsqueda: HTTP ${response.status}`);
        index = (await response.json()).map((item) => ({
          ...item,
          normalized: normalize([item.title, item.text, ...item.topics].join(" ")),
          normalizedTitle: normalize(item.title)
        }));
      }
      if (current !== requestNumber) return;
      const words = normalize(query).split(/\s+/).filter(Boolean);
      const matches = index.filter((item) => words.every((word) => item.normalized.includes(word)));
      matches.sort((a, b) => Number(words.every((word) => b.normalizedTitle.includes(word))) -
        Number(words.every((word) => a.normalizedTitle.includes(word))));
      status.textContent = `${matches.length} ${matches.length === 1 ? "artículo encontrado" : "artículos encontrados"}.`;
      for (const item of matches) {
        const li = document.createElement("li");
        const heading = document.createElement("h2");
        const link = document.createElement("a");
        link.href = item.url;
        link.textContent = item.title;
        heading.append(link);
        const date = document.createElement("p");
        date.textContent = item.date + " · " + item.topics.slice(0, 3).join(", ");
        const excerpt = document.createElement("p");
        excerpt.textContent = item.text.slice(0, 220) + (item.text.length > 220 ? "…" : "");
        li.append(heading, date, excerpt);
        results.append(li);
      }
    } catch (error) {
      if (current !== requestNumber) return;
      status.textContent = "No se pudo cargar la búsqueda. Puedes consultar el archivo de artículos o volver a intentarlo.";
      console.error(error);
    }
  }
  form.addEventListener("submit", run);
  input.value = new URLSearchParams(location.search).get("q") || "";
  if (input.value) await run();
}

compatibility();
search();
