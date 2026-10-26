/* Interactive report page (FR-19, FR-66): MapLibre maps with the analysis layers, a layer
 * panel with legends, hover readouts, a swipe between imagery years, and Vega-Lite charts.
 * Everything the page needs is in <script type="application/json"> blocks written by Django;
 * without JavaScript the page still shows the text, the static maps and data tables. */
(function () {
  "use strict";

  const LANG = document.documentElement.lang || "fr";
  let T = { compare: "", left: "", right: "", divider: "", colon: ":" }; // set from the map config

  function readJSON(id) {
    const node = document.getElementById(id);
    return node ? JSON.parse(node.textContent) : null;
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "text") node.textContent = v;
      else if (k === "class") node.className = v;
      else node.setAttribute(k, v);
    });
    (children || []).forEach((c) => node.appendChild(c));
    return node;
  }

  /* ---------- maps ---------- */

  function baseStyle(config) {
    return {
      version: 8,
      sources: {
        basemap: {
          type: "raster", tiles: [config.basemapUrl], tileSize: 256, maxzoom: 19,
          attribution: config.attribution,
        },
      },
      layers: [{ id: "basemap", type: "raster", source: "basemap" }],
    };
  }

  function newMap(container, config) {
    const map = new maplibregl.Map({
      container, style: baseStyle(config), scrollZoom: false, attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
    return map;
  }

  function extend(bounds, coords) {
    if (typeof coords[0] === "number") bounds.extend(coords);
    else coords.forEach((c) => extend(bounds, c));
  }

  function initialBounds(config) {
    const bounds = new maplibregl.LngLatBounds();
    if (config.parcel) extend(bounds, config.parcel.coordinates);
    config.layers.forEach((layer) => {
      // Points (services) can spread far; the view fits the areas and images instead.
      if (!layer.visible || (layer.style && layer.style.kind === "circle")) return;
      if (layer.type === "image") extend(bounds, layer.coordinates);
      else layer.data.features.forEach((f) => extend(bounds, f.geometry.coordinates));
    });
    return bounds;
  }

  function addImage(map, layer, visible) {
    map.addSource(layer.id, { type: "image", url: layer.url, coordinates: layer.coordinates });
    map.addLayer({
      id: layer.id, type: "raster", source: layer.id,
      paint: { "raster-opacity": layer.opacity, "raster-fade-duration": 0, "raster-resampling": "nearest" },
      layout: { visibility: visible ? "visible" : "none" },
    });
    return [layer.id];
  }

  function addVector(map, layer) {
    const s = layer.style;
    const color = ["coalesce", ["get", "color"], s.color];
    const layout = { visibility: layer.visible ? "visible" : "none" };
    const ids = [];
    map.addSource(layer.id, { type: "geojson", data: layer.data });
    if (s.kind === "fill") {
      map.addLayer({ id: layer.id + "-fill", type: "fill", source: layer.id, layout,
        paint: { "fill-color": color, "fill-opacity": s.opacity } });
      ids.push(layer.id + "-fill");
      if (s.outline) {
        map.addLayer({ id: layer.id + "-outline", type: "line", source: layer.id, layout,
          paint: { "line-color": s.outline, "line-width": 1 } });
        ids.push(layer.id + "-outline");
      }
    } else if (s.kind === "line") {
      const paint = { "line-color": color, "line-width": s.width };
      if (s.dash) paint["line-dasharray"] = [3, 2];
      map.addLayer({ id: layer.id + "-line", type: "line", source: layer.id, layout, paint });
      ids.push(layer.id + "-line");
    } else {
      map.addLayer({ id: layer.id + "-circle", type: "circle", source: layer.id, layout,
        paint: { "circle-color": color, "circle-radius": s.width, "circle-stroke-color": s.outline || "#FFFFFF", "circle-stroke-width": 1 } });
      ids.push(layer.id + "-circle");
    }
    return ids;
  }

  function addParcel(map, parcel) {
    if (!parcel) return;
    map.addSource("parcel", { type: "geojson", data: parcel });
    map.addLayer({ id: "parcel-halo", type: "line", source: "parcel", paint: { "line-color": "#FFFFFF", "line-width": 5 } });
    map.addLayer({ id: "parcel-line", type: "line", source: "parcel", paint: { "line-color": "#000000", "line-width": 2.5 } });
  }

  function gridValue(layer, lngLat) {
    const lons = layer.coordinates.map((c) => c[0]);
    const lats = layer.coordinates.map((c) => c[1]);
    const west = Math.min(...lons), east = Math.max(...lons);
    const south = Math.min(...lats), north = Math.max(...lats);
    const grid = layer.hover.grid;
    if (lngLat.lng < west || lngLat.lng > east || lngLat.lat < south || lngLat.lat > north) return null;
    const row = Math.min(grid.length - 1, Math.floor(((north - lngLat.lat) / (north - south)) * grid.length));
    const col = Math.min(grid[0].length - 1, Math.floor(((lngLat.lng - west) / (east - west)) * grid[0].length));
    const value = grid[row][col];
    if (value === null || value === undefined) return null;
    if (layer.hover.categories && Object.keys(layer.hover.categories).length) {
      return layer.hover.categories[String(Math.round(value))] || null;
    }
    return value.toLocaleString(LANG) + " " + (layer.hover.unit || "");
  }

  function enableHover(map, config, idsByLayer, isVisible) {
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: "280px" });
    map.on("mousemove", (event) => {
      const lines = [];
      config.layers.forEach((layer) => {
        if (!isVisible(layer)) return;
        if (layer.type === "image" && layer.hover) {
          const value = gridValue(layer, event.lngLat);
          if (value) lines.push([layer.title, value]);
        } else if (layer.type === "geojson" && layer.hover.length) {
          const hit = map.queryRenderedFeatures(event.point, { layers: idsByLayer[layer.id] })[0];
          if (hit) layer.hover.forEach((h) => {
            const v = hit.properties[h.property];
            if (v !== undefined && v !== "") lines.push([h.label, v]);
          });
        }
      });
      if (!lines.length) { popup.remove(); return; }
      const box = el("div", { class: "text-xs" }, lines.map(([k, v]) =>
        el("div", {}, [el("strong", { text: k + T.colon }), document.createTextNode(" " + v)])));
      popup.setLngLat(event.lngLat).setDOMContent(box).addTo(map);
    });
    map.getCanvas().addEventListener("mouseleave", () => popup.remove());
  }

  function legendList(layer) {
    return el("ul", { class: "mt-1 space-y-0.5 pl-6" }, layer.legend.map((entry) => {
      const swatch = el("span", { class: "inline-block h-3 w-3 shrink-0 border border-slate-400", "aria-hidden": "true" });
      swatch.style.background = entry.color;
      if (entry.shape === "line") { swatch.style.height = "3px"; swatch.style.border = "0"; }
      if (entry.shape === "circle") swatch.style.borderRadius = "50%";
      return el("li", { class: "flex items-center gap-2 text-xs text-slate-700" }, [swatch, el("span", { text: entry.label })]);
    }));
  }

  function layerPanel(panel, map, config, idsByLayer, state) {
    const list = el("ul", { class: "space-y-3" });
    config.layers.filter((l) => !l.group).forEach((layer) => {
      const id = "toggle-" + panel.dataset.layerPanel + "-" + layer.id;
      const box = el("input", { type: "checkbox", id, class: "mt-0.5 h-4 w-4" });
      box.checked = !!layer.visible;
      box.addEventListener("change", () => {
        state[layer.id] = box.checked;
        idsByLayer[layer.id].forEach((lid) => map.setLayoutProperty(lid, "visibility", box.checked ? "visible" : "none"));
      });
      const item = el("li", {}, [el("div", { class: "flex items-start gap-2" }, [box, el("label", { for: id, class: "font-medium", text: layer.title })])]);
      if (layer.legend.length) item.appendChild(legendList(layer));
      list.appendChild(item);
    });
    panel.appendChild(list);
  }

  function yearSelect(id, label, years, selected) {
    const select = el("select", { id, class: "w-full rounded border border-slate-300 px-2 py-1" },
      years.map((y) => el("option", { value: String(y), text: String(y) })));
    select.value = String(selected);
    return [el("label", { for: id, class: "block text-xs font-medium", text: label }), select];
  }

  /* Years side by side: a second map, clipped to the right of a divider, follows the first. */
  function yearSwipe(container, panel, map, config) {
    const frames = config.layers.filter((l) => l.group === "years").sort((a, b) => a.year - b.year);
    if (frames.length < 2) return;
    const years = frames.map((f) => f.year);
    const wrapper = container.parentElement;
    // MapLibre makes its container position: relative, so the clipped overlay is an absolutely
    // placed wrapper around the second map's own container.
    const overlay = el("div", { class: "pointer-events-none absolute left-0 top-0 h-[28rem] w-full overflow-hidden rounded", "aria-hidden": "true" });
    const overlayMap = el("div", { class: "h-full w-full" });
    overlay.appendChild(overlayMap);
    wrapper.insertBefore(overlay, container.nextSibling);
    const divider = el("div", { class: "pointer-events-none absolute top-0 h-[28rem] w-0.5 bg-white shadow", "aria-hidden": "true" });
    wrapper.appendChild(divider);
    const right = newMap(overlayMap, config);
    right.getContainer().querySelectorAll(".maplibregl-ctrl-top-right, .maplibregl-ctrl-bottom-left").forEach((n) => n.remove());

    const pid = panel.dataset.layerPanel;
    const firstClear = frames.find((f) => (f.clear_pct ?? 100) >= 80) || frames[0];
    const [leftLabel, leftSelect] = yearSelect(pid + "-left", T.left, years, firstClear.year);
    const [rightLabel, rightSelect] = yearSelect(pid + "-right", T.right, years, years[years.length - 1]);
    const slider = el("input", { type: "range", min: "0", max: "100", value: "50", id: pid + "-divider", class: "w-full" });
    panel.prepend(el("fieldset", { class: "mb-4 rounded border border-slate-200 p-3" }, [
      el("legend", { class: "px-1 font-medium", text: T.compare }), leftLabel, leftSelect, rightLabel, rightSelect,
      el("label", { for: slider.id, class: "mt-2 block text-xs font-medium", text: T.divider }), slider,
    ]));

    function clip() {
      const pct = Number(slider.value);
      overlay.style.clipPath = "inset(0 0 0 " + pct + "%)";
      divider.style.left = pct + "%";
    }
    function show(target, year) {
      frames.forEach((f) => target.setLayoutProperty(f.id, "visibility", f.year === Number(year) ? "visible" : "none"));
    }
    right.on("load", () => {
      frames.forEach((f) => addImage(right, f, false));
      addParcel(right, config.parcel);
      show(right, rightSelect.value);
      right.jumpTo({ center: map.getCenter(), zoom: map.getZoom() });
    });
    map.on("move", () => right.jumpTo({ center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing() }));
    leftSelect.addEventListener("change", () => show(map, leftSelect.value));
    rightSelect.addEventListener("change", () => show(right, rightSelect.value));
    slider.addEventListener("input", clip);
    show(map, leftSelect.value);
    clip();
  }

  function initMap(container) {
    const config = readJSON(container.dataset.reportMap);
    if (!config || typeof maplibregl === "undefined") return;
    T = config.labels || T;
    const panel = document.querySelector('[data-layer-panel="' + container.id + '"]');
    const map = newMap(container, config);
    const bounds = initialBounds(config);
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 30, maxZoom: 18, duration: 0 });
    const idsByLayer = {};
    const state = {};
    map.on("load", () => {
      config.layers.forEach((layer) => {
        state[layer.id] = !!layer.visible;
        idsByLayer[layer.id] = layer.type === "image" ? addImage(map, layer, layer.visible && !layer.group) : addVector(map, layer);
      });
      addParcel(map, config.parcel);
      if (panel) {
        layerPanel(panel, map, config, idsByLayer, state);
        yearSwipe(container, panel, map, config);
      }
      enableHover(map, config, idsByLayer, (layer) => !layer.group && state[layer.id]);
    });
  }

  /* ---------- charts ---------- */

  function initChart(node) {
    const spec = readJSON(node.dataset.vega);
    if (!spec || typeof vegaEmbed === "undefined") return;
    // The specs name the PDF font; on screen, charts use the page's font.
    const font = getComputedStyle(document.body).fontFamily;
    spec.config = Object.assign({}, spec.config, { font });
    vegaEmbed(node, spec, { actions: false, renderer: "svg" }).catch(() => {
      node.textContent = "";
    });
  }

  /* ---------- share links ---------- */

  function initCopy(button) {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.copy);
      input.select();
      if (navigator.clipboard) navigator.clipboard.writeText(input.value);
    });
  }

  function start() {
    // Maps start only when they come near the screen: one WebGL context each, and a report
    // has up to nine of them.
    const maps = document.querySelectorAll("[data-report-map]");
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          observer.unobserve(entry.target);
          initMap(entry.target);
        });
      }, { rootMargin: "300px 0px" });
      maps.forEach((node) => observer.observe(node));
    } else {
      maps.forEach(initMap);
    }
    document.querySelectorAll("[data-vega]").forEach(initChart);
    document.querySelectorAll("[data-copy]").forEach(initCopy);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
