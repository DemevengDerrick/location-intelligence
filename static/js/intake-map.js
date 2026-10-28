/* Order form, step 1: locate the parcel on Esri imagery with a pin or a drawn boundary.
 * Writes GeoJSON into the hidden #id_geometry input; the server validates everything. */
(function () {
  "use strict";

  const config = JSON.parse(document.getElementById("intake-config").textContent);
  const input = document.getElementById("id_geometry");
  const status = document.getElementById("shape-status");
  const storageKey = config.token ? "intake:" + config.token + ":geometry" : null;
  const CAMEROON = { center: [12.35, 5.7], zoom: 5 };
  // The map cannot be panned away from Cameroon: it always springs back inside these bounds.
  const MAX_BOUNDS = [[5.5, 0.0], [19.5, 14.8]];
  const whereLine = document.getElementById("map-where");
  const outsideAlert = document.getElementById("map-outside");
  let country = null; // the outline, once loaded, for the instant "outside Cameroon" check

  let method = config.method || "pin";
  let marker = null;

  const map = new maplibregl.Map({
    container: "intake-map",
    style: {
      version: 8,
      sources: {
        imagery: {
          type: "raster",
          tiles: [config.basemapUrl],
          tileSize: 256,
          maxzoom: 19,
          attribution: config.attribution,
        },
      },
      layers: [{ id: "imagery", type: "raster", source: "imagery" }],
    },
    center: CAMEROON.center,
    zoom: CAMEROON.zoom,
    maxZoom: 20,
    minZoom: 4.5,
    maxBounds: MAX_BOUNDS,
    cooperativeGestures: false,
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
  map.addControl(new maplibregl.GeolocateControl({ positionOptions: { enableHighAccuracy: true } }));

  const draw = new terraDraw.TerraDraw({
    adapter: new terraDrawMaplibreGlAdapter.TerraDrawMapLibreGLAdapter({ map }),
    modes: [
      new terraDraw.TerraDrawPolygonMode(),
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

  // --- helpers --------------------------------------------------------------------------

  function save(geometry) {
    if (geometry && !checkCountry(geometry)) geometry = null;
    else if (!geometry) checkCountry(null);
    input.value = geometry ? JSON.stringify(geometry) : "";
    try {
      if (storageKey) {
        geometry ? localStorage.setItem(storageKey, input.value) : localStorage.removeItem(storageKey);
      }
    } catch (e) {}
  }

  function setStatus(text) {
    status.textContent = text || "";
  }

  function boundsOf(geometry) {
    const bounds = new maplibregl.LngLatBounds();
    (function walk(coords) {
      if (typeof coords[0] === "number") bounds.extend(coords);
      else coords.forEach(walk);
    })(geometry.coordinates);
    return bounds;
  }

  // --- boundaries, mask and "where am I" ----------------------------------------------

  function addBoundaryLayers() {
    // Empty at first, filled when the outlines arrive; added before Terra Draw starts so the
    // drawing stays on top.
    map.addSource("boundaries", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    const level = (name) => ["==", ["get", "level"], name];
    map.addLayer({ id: "mask", type: "fill", source: "boundaries", filter: level("mask"),
      paint: { "fill-color": "#1f2937", "fill-opacity": 0.6 } });
    ["region", "department", "commune"].forEach((name) => {
      // invisible fills, so the names under a point can be looked up
      map.addLayer({ id: name + "-fill", type: "fill", source: "boundaries", filter: level(name),
        paint: { "fill-opacity": 0 } });
    });
    map.addLayer({ id: "commune-line", type: "line", source: "boundaries", filter: level("commune"),
      minzoom: 8, paint: { "line-color": "#ffffff", "line-width": 0.7, "line-opacity": 0.8 } });
    map.addLayer({ id: "department-line", type: "line", source: "boundaries", filter: level("department"),
      minzoom: 6, paint: { "line-color": "#ffffff", "line-width": 1.2, "line-dasharray": [3, 2] } });
    map.addLayer({ id: "region-line", type: "line", source: "boundaries", filter: level("region"),
      paint: { "line-color": "#fde68a", "line-width": 2 } });
    map.addLayer({ id: "country-line", type: "line", source: "boundaries", filter: level("country"),
      paint: { "line-color": "#ffffff", "line-width": 3 } });
  }

  async function loadBoundaries() {
    try {
      const response = await fetch(config.boundariesUrl, { headers: { Accept: "application/json" } });
      const data = await response.json();
      map.getSource("boundaries").setData(data);
      const outline = data.features.find((f) => f.properties.level === "country");
      country = outline ? outline.geometry : null;
      map.once("idle", showWhere);
    } catch (e) {} // the map still works without the outlines; the server checks the country
  }

  function namesAt(lngLat) {
    const point = map.project(lngLat);
    const names = {};
    map.queryRenderedFeatures(point, { layers: ["region-fill", "department-fill", "commune-fill"] })
      .forEach((f) => { names[f.properties.level] = f.properties.name; });
    return [names.commune, names.department, names.region].filter(Boolean).join(" · ");
  }

  function showWhere() {
    if (!whereLine || !map.getLayer("commune-fill")) return;
    const pinShown = marker && marker.getElement().isConnected;
    const at = pinShown ? marker.getLngLat() : map.getCenter();
    const names = namesAt(at);
    whereLine.textContent = names ? config.messages.here + " " + names : "";
  }

  function inRing(point, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      if (yi > point[1] !== yj > point[1] && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  function inCameroon(point) {
    if (!country) return true; // not loaded yet: the server still checks on submit
    const polygons = country.type === "MultiPolygon" ? country.coordinates : [country.coordinates];
    return polygons.some((rings) => inRing(point, rings[0]) && !rings.slice(1).some((hole) => inRing(point, hole)));
  }

  function verticesOf(geometry) {
    const points = [];
    (function walk(coords) {
      if (typeof coords[0] === "number") points.push(coords);
      else coords.forEach(walk);
    })(geometry.coordinates);
    return points;
  }

  function checkCountry(geometry) {
    // Flags a pin or boundary outside Cameroon at once, and keeps it out of the form.
    const outside = geometry && verticesOf(geometry).some((point) => !inCameroon(point));
    if (outsideAlert) {
      outsideAlert.textContent = outside ? config.messages.outside : "";
      outsideAlert.classList.toggle("hidden", !outside);
    }
    return !outside;
  }

  function placeMarker(lngLat) {
    if (!marker) {
      marker = new maplibregl.Marker({ draggable: true, color: "#047857" });
      marker.on("dragend", () => savePin(marker.getLngLat()));
    }
    marker.setLngLat(lngLat).addTo(map);
    savePin(lngLat);
  }

  function savePin(lngLat) {
    save({ type: "Point", coordinates: [lngLat.lng, lngLat.lat] });
    showWhere();
  }

  function removeMarker() {
    if (marker) marker.remove();
  }

  function polygonFromDraw() {
    const polygons = draw.getSnapshot().filter((f) => f.geometry.type === "Polygon");
    if (!polygons.length) return null;
    if (polygons.length === 1) return polygons[0].geometry;
    return { type: "MultiPolygon", coordinates: polygons.map((f) => f.geometry.coordinates) };
  }

  function showExisting(geometry) {
    // The boundary saved on the server (e.g. from an uploaded file), drawn as an outline.
    const data = { type: "Feature", properties: {}, geometry };
    if (map.getSource("existing")) {
      map.getSource("existing").setData(data);
      return;
    }
    map.addSource("existing", { type: "geojson", data });
    map.addLayer({
      id: "existing-line",
      type: "line",
      source: "existing",
      paint: { "line-color": "#facc15", "line-width": 3 },
    });
  }

  // --- modes ----------------------------------------------------------------------------

  function applyMethod(next) {
    method = next;
    if (method === "drawn") {
      removeMarker();
      draw.setMode("polygon");
      const current = polygonFromDraw();
      save(current);
    } else {
      draw.setMode("static");
      if (method === "pin" || method === "site_plan") {
        if (marker && marker.getLngLat()) {
          marker.addTo(map);
          savePin(marker.getLngLat());
        } else {
          save(null);
        }
      } else {
        removeMarker();
        save(null);
      }
    }
  }

  map.on("click", (event) => {
    if (method === "pin" || method === "site_plan") placeMarker(event.lngLat);
  });

  draw.on("finish", () => {
    save(polygonFromDraw());
    draw.setMode("select");
    setStatus("");
  });
  draw.on("change", () => {
    if (method === "drawn" && draw.getMode() === "select") save(polygonFromDraw());
  });

  document.getElementById("clear-shape").addEventListener("click", () => {
    // draw.clear() would also remove Terra Draw's map layers (nothing would show afterwards).
    draw.setMode("static");
    const ids = draw.getSnapshot().map((f) => f.id);
    if (ids.length) draw.removeFeatures(ids);
    removeMarker();
    marker = null;
    save(null);
    if (method === "drawn") draw.setMode("polygon");
  });

  window.addEventListener("intake-method", (event) => applyMethod(event.detail));

  // --- search ---------------------------------------------------------------------------

  const searchInput = document.getElementById("place-search");
  const resultsList = document.getElementById("search-results");

  window.addEventListener("intake-search", async () => {
    const query = searchInput.value.trim();
    if (query.length < 3) return;
    resultsList.innerHTML = "";
    setStatus(config.messages.searching);
    try {
      const response = await fetch(config.searchUrl + "?q=" + encodeURIComponent(query), {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      setStatus("");
      if (!payload.results || !payload.results.length) {
        const li = document.createElement("li");
        li.textContent = config.messages.noResults;
        resultsList.appendChild(li);
        return;
      }
      payload.results.forEach((result) => {
        const li = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "text-left underline";
        button.textContent = result.label;
        button.addEventListener("click", () => {
          if (result.bbox) {
            map.fitBounds([[result.bbox[0], result.bbox[1]], [result.bbox[2], result.bbox[3]]], {
              padding: 20,
              maxZoom: 17,
            });
          } else {
            map.flyTo({ center: [result.lon, result.lat], zoom: 16 });
          }
          resultsList.innerHTML = "";
        });
        li.appendChild(button);
        resultsList.appendChild(li);
      });
    } catch (e) {
      setStatus(config.messages.noResults);
    }
  });

  // --- initial state --------------------------------------------------------------------

  map.on("moveend", showWhere);

  map.on("load", () => {
    addBoundaryLayers();
    loadBoundaries();
    draw.start();

    let stored = null;
    try {
      stored = storageKey && !config.geometry && !config.pin ? localStorage.getItem(storageKey) : null;
    } catch (e) {}
    const restored = stored ? JSON.parse(stored) : null;

    const pin = config.pin || (restored && restored.type === "Point" ? restored : null);
    const shape = config.geometry || (restored && restored.type !== "Point" ? restored : null);

    if (shape) {
      if (method === "drawn") {
        const polygons = shape.type === "MultiPolygon" ? shape.coordinates : [shape.coordinates];
        draw.addFeatures(
          polygons.map((coordinates) => ({
            type: "Feature",
            geometry: { type: "Polygon", coordinates },
            properties: { mode: "polygon" },
          }))
        );
      } else if (!config.pin) {
        showExisting(shape);
      }
      map.fitBounds(boundsOf(shape), { padding: 40, maxZoom: 18, duration: 0 });
    }
    if (pin) {
      placeMarker({ lng: pin.coordinates[0], lat: pin.coordinates[1] });
      if (!shape) map.jumpTo({ center: pin.coordinates, zoom: 17 });
    }
    applyMethod(method);
  });
})();
