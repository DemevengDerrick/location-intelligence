/* Staff boundary editor (FR-38, FR-39): draw or edit the parcel boundary over imagery with
 * snapping, type corner coordinates, and georeference a scanned site plan from control points.
 * The server validates and saves; this script only builds the GeoJSON in #geometry-input. */
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("editor-config").textContent);
  const T = config.labels;
  const input = document.getElementById("geometry-input");
  const mapStatus = document.getElementById("map-status");
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const CAMEROON = { center: [12.35, 5.7], zoom: 5 };

  function setStatus(node, text, isError) {
    if (!node) return;
    node.textContent = text || "";
    node.classList.toggle("error", Boolean(isError));
  }

  function boundsOf(geometries) {
    const bounds = new maplibregl.LngLatBounds();
    (function walk(coords) {
      if (typeof coords[0] === "number") bounds.extend(coords);
      else coords.forEach(walk);
    })(geometries.map((g) => g.coordinates));
    return bounds;
  }

  async function post(url, body, json) {
    const response = await fetch(url, {
      method: "POST",
      headers: json
        ? { "Content-Type": "application/json", "X-CSRFToken": csrf }
        : { "X-CSRFToken": csrf },
      body: json ? JSON.stringify(body) : body,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || response.statusText);
    return payload;
  }

  // --- map and drawing ------------------------------------------------------------------

  const map = new maplibregl.Map({
    container: "editor-map",
    style: {
      version: 8,
      sources: {
        imagery: {
          type: "raster", tiles: [config.basemapUrl], tileSize: 256, maxzoom: 19,
          attribution: config.attribution,
        },
      },
      layers: [{ id: "imagery", type: "raster", source: "imagery" }],
    },
    center: CAMEROON.center,
    zoom: CAMEROON.zoom,
    maxZoom: 21,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));

  const draw = new terraDraw.TerraDraw({
    adapter: new terraDrawMaplibreGlAdapter.TerraDrawMapLibreGLAdapter({ map }),
    modes: [
      new terraDraw.TerraDrawPolygonMode({ snapping: { toCoordinate: true, toLine: true } }),
      new terraDraw.TerraDrawSelectMode({
        flags: {
          polygon: {
            feature: {
              draggable: true,
              coordinates: { midpoints: true, draggable: true, deletable: true },
            },
          },
        },
      }),
    ],
  });

  window.geometryEditor = { map, draw }; // for debugging from the browser console

  function polygons() {
    return draw.getSnapshot().filter((f) => f.geometry.type === "Polygon");
  }

  function clearShapes() {
    // draw.clear() would also remove Terra Draw's map layers (nothing would show afterwards).
    draw.setMode("static");
    const ids = draw.getSnapshot().map((f) => f.id);
    if (ids.length) draw.removeFeatures(ids);
  }

  function save() {
    const shapes = polygons();
    if (!shapes.length) input.value = "";
    else if (shapes.length === 1) input.value = JSON.stringify(shapes[0].geometry);
    else input.value = JSON.stringify({
      type: "MultiPolygon", coordinates: shapes.map((f) => f.geometry.coordinates),
    });
  }

  function load(geometry) {
    clearShapes();
    if (geometry) {
      const parts = geometry.type === "MultiPolygon" ? geometry.coordinates : [geometry.coordinates];
      draw.addFeatures(parts.map((coordinates) => ({
        type: "Feature", geometry: { type: "Polygon", coordinates }, properties: { mode: "polygon" },
      })));
    }
    save();
  }

  draw.on("finish", () => {
    save();
    draw.setMode("select");
  });
  draw.on("change", () => save());

  document.getElementById("draw-new").addEventListener("click", () => {
    georef.stop();
    clearShapes();
    save();
    draw.setMode("polygon");
  });
  document.getElementById("edit-shape").addEventListener("click", () => {
    georef.stop();
    draw.setMode("select");
  });
  document.getElementById("reset-shape").addEventListener("click", () => {
    georef.stop();
    load(config.approximate ? null : config.geometry);
    draw.setMode(config.geometry && !config.approximate ? "select" : "polygon");
  });

  document.querySelector("form").addEventListener("submit", (event) => {
    save();
    if (!input.value) {
      event.preventDefault();
      setStatus(mapStatus, T.noShape, true);
    }
  });

  // --- typed coordinates ----------------------------------------------------------------

  document.getElementById("coords-show").addEventListener("click", async () => {
    const body = new FormData();
    body.append("text", document.getElementById("coords-text").value);
    body.append("crs", document.getElementById("coords-crs").value);
    try {
      const payload = await post(config.urls.coordinates, body, false);
      georef.stop();
      load(payload.geometry);
      draw.setMode("select");
      map.fitBounds(boundsOf([payload.geometry]), { padding: 40, maxZoom: 19 });
      setStatus(mapStatus, "");
    } catch (error) {
      setStatus(mapStatus, error.message, true);
    }
  });

  document.getElementById("coords-copy").addEventListener("click", () => {
    const shape = polygons()[0];
    if (!shape) return;
    const ring = shape.geometry.coordinates[0].slice(0, -1);
    document.getElementById("coords-crs").value = "wgs84";
    document.getElementById("coords-text").value =
      ring.map(([lon, lat]) => lon.toFixed(7) + ", " + lat.toFixed(7)).join("\n");
  });

  // --- site-plan georeferencing ---------------------------------------------------------

  const georef = (function () {
    const select = document.getElementById("plan-select");
    if (!select) return { stop() {}, active: () => false };

    const editor = document.getElementById("editor");
    const controls = document.getElementById("plan-controls");
    const viewport = document.getElementById("plan-viewport");
    const stage = document.getElementById("plan-stage");
    const image = document.getElementById("plan-image");
    const planStatus = document.getElementById("plan-status");
    const fitStatus = document.getElementById("fit-status");
    const table = document.querySelector("#cp-table tbody");
    const opacity = document.getElementById("plan-opacity");

    let plan = null;
    let points = [];
    let pending = null;
    let active = false;
    let markers = [];
    const view = { scale: 1, x: 0, y: 0 };

    function applyView() {
      stage.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
      stage.querySelectorAll(".cp-dot").forEach((dot) => {
        dot.style.transform = `scale(${1 / view.scale})`;
      });
    }

    function fitView() {
      if (!image.naturalWidth) return;
      const scale = Math.min(viewport.clientWidth / image.naturalWidth,
                             viewport.clientHeight / image.naturalHeight);
      view.scale = scale;
      view.x = (viewport.clientWidth - image.naturalWidth * scale) / 2;
      view.y = (viewport.clientHeight - image.naturalHeight * scale) / 2;
      applyView();
    }

    function zoomAt(factor, cx, cy) {
      view.x = cx - (cx - view.x) * factor;
      view.y = cy - (cy - view.y) * factor;
      view.scale *= factor;
      applyView();
    }

    document.querySelectorAll("[data-plan-zoom]").forEach((button) => {
      button.addEventListener("click", () => {
        const value = button.dataset.planZoom;
        if (value === "fit") fitView();
        else zoomAt(parseFloat(value), viewport.clientWidth / 2, viewport.clientHeight / 2);
      });
    });
    viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      zoomAt(event.deltaY < 0 ? 1.15 : 1 / 1.15, event.clientX - rect.left, event.clientY - rect.top);
    }, { passive: false });

    // Drag to pan; a click without movement picks a point.
    let drag = null;
    viewport.addEventListener("mousedown", (event) => {
      drag = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: false };
    });
    window.addEventListener("mousemove", (event) => {
      if (!drag) return;
      const dx = event.clientX - drag.x;
      const dy = event.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      if (drag.moved) {
        view.x = drag.vx + dx;
        view.y = drag.vy + dy;
        applyView();
      }
    });
    window.addEventListener("mouseup", (event) => {
      if (!drag) return;
      const click = !drag.moved && viewport.contains(event.target);
      drag = null;
      if (click && active && plan) {
        const rect = viewport.getBoundingClientRect();
        const px = (event.clientX - rect.left - view.x) / view.scale;
        const py = (event.clientY - rect.top - view.y) / view.scale;
        if (px < 0 || py < 0 || px > image.naturalWidth || py > image.naturalHeight) return;
        pending = [Math.round(px * 10) / 10, Math.round(py * 10) / 10];
        render();
        setStatus(planStatus, T.pickMap);
      }
    });

    function dot(pixel, label, isPending) {
      const node = document.createElement("div");
      node.className = "cp-dot" + (isPending ? " pending" : "");
      node.style.left = pixel[0] + "px";
      node.style.top = pixel[1] + "px";
      node.textContent = label;
      stage.appendChild(node);
    }

    function render(fit) {
      stage.querySelectorAll(".cp-dot").forEach((n) => n.remove());
      markers.forEach((m) => m.remove());
      markers = [];
      table.innerHTML = "";
      points.forEach((point, i) => {
        dot(point.pixel, i + 1, false);
        const el = document.createElement("div");
        el.className = "cp-marker";
        el.textContent = i + 1;
        markers.push(new maplibregl.Marker({ element: el }).setLngLat(point.lnglat).addTo(map));
        const row = document.createElement("tr");
        const residual = fit && fit.residuals_m ? fit.residuals_m[i] : null;
        row.innerHTML = `<td>${i + 1}</td><td>${residual === null ? "–" : residual}</td><td></td>`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "button";
        remove.textContent = T.remove;
        remove.addEventListener("click", () => {
          points.splice(i, 1);
          refit();
        });
        row.lastChild.appendChild(remove);
        table.appendChild(row);
      });
      if (pending) dot(pending, points.length + 1, true);
      applyView();
    }

    function showOverlay(corners) {
      if (map.getLayer("plan")) map.removeLayer("plan");
      if (map.getSource("plan")) map.removeSource("plan");
      if (!corners) return;
      map.addSource("plan", { type: "image", url: plan.url, coordinates: corners });
      const firstDraw = map.getStyle().layers.find((layer) => layer.id.startsWith("td-"));
      map.addLayer(
        { id: "plan", type: "raster", source: "plan",
          paint: { "raster-opacity": parseFloat(opacity.value), "raster-fade-duration": 0 } },
        firstDraw ? firstDraw.id : undefined
      );
    }

    async function refit() {
      if (points.length < 3) {
        showOverlay(null);
        render();
        setStatus(fitStatus, T.needMore);
        return;
      }
      try {
        const fit = await post(config.urls.georeference, {
          attachment: plan.id,
          width: image.naturalWidth,
          height: image.naturalHeight,
          points,
        }, true);
        plan.georeference = { ...fit, points };
        showOverlay(fit.corners);
        render(fit);
        setStatus(fitStatus, fit.rmse_m === null ? T.exact : T.rmse.replace("%(m)s", fit.rmse_m));
      } catch (error) {
        render();
        setStatus(fitStatus, error.message, true);
      }
    }

    map.on("click", (event) => {
      if (!active || !pending) return;
      points.push({ pixel: pending, lnglat: [event.lngLat.lng, event.lngLat.lat] });
      pending = null;
      setStatus(planStatus, T.pickPlan);
      refit();
    });

    opacity.addEventListener("input", () => {
      if (map.getLayer("plan")) map.setPaintProperty("plan", "raster-opacity", parseFloat(opacity.value));
    });

    function start() {
      active = true;
      draw.setMode("static");
      map.getCanvas().style.cursor = "crosshair";
      setStatus(planStatus, T.pickPlan);
    }

    function stop() {
      active = false;
      pending = null;
      map.getCanvas().style.cursor = "";
      setStatus(planStatus, "");
      if (plan) render(plan.georeference);
    }

    document.getElementById("cp-start").addEventListener("click", start);
    document.getElementById("cp-done").addEventListener("click", () => {
      stop();
      draw.setMode(polygons().length ? "select" : "polygon");
    });

    select.addEventListener("change", () => {
      showOverlay(null);
      plan = config.plans.find((p) => String(p.id) === select.value) || null;
      editor.classList.toggle("with-plan", Boolean(plan));
      controls.hidden = !plan;
      points = [];
      pending = null;
      render();
      map.resize();
      if (!plan) return stop();
      image.onload = () => {
        fitView();
        const saved = plan.georeference;
        if (saved && saved.points && saved.width === image.naturalWidth) {
          points = saved.points.slice();
          refit();
        } else {
          setStatus(fitStatus, T.needMore);
        }
        start();
      };
      image.onerror = () => setStatus(planStatus, "⚠", true);
      image.src = plan.url;
    });

    return { stop, active: () => active };
  })();

  // --- start ----------------------------------------------------------------------------

  map.on("load", () => {
    draw.start();
    config.history.forEach((geometry, i) => {
      map.addSource("history-" + i, { type: "geojson", data: { type: "Feature", properties: {}, geometry } });
      map.addLayer({
        id: "history-" + i, type: "line", source: "history-" + i,
        paint: { "line-color": "#facc15", "line-width": 2, "line-dasharray": [2, 2] },
      });
    });
    const known = [config.geometry, ...config.history].filter(Boolean);
    if (known.length) map.fitBounds(boundsOf(known), { padding: 40, maxZoom: 19, duration: 0 });
    // A pin-only parcel is a circle around the pin: show it, but start a fresh drawing.
    if (config.geometry && !config.approximate) {
      load(config.geometry);
      draw.setMode("select");
    } else {
      if (config.geometry) {
        map.addSource("approximate", { type: "geojson", data: { type: "Feature", properties: {}, geometry: config.geometry } });
        map.addLayer({ id: "approximate", type: "line", source: "approximate",
                       paint: { "line-color": "#f97316", "line-width": 2, "line-dasharray": [1, 1] } });
      }
      draw.setMode("polygon");
    }
  });
})();
