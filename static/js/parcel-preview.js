/* Read-only map of a parcel boundary (or approximate pin) on Esri imagery. */
(function () {
  "use strict";
  const config = JSON.parse(document.getElementById("preview-config").textContent);
  const geometry = config.geometry || config.pin;
  if (!geometry) return;

  const map = new maplibregl.Map({
    container: "parcel-preview",
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
    interactive: true,
    scrollZoom: false, // let the mouse wheel scroll the page; zoom with the buttons
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }));

  const bounds = new maplibregl.LngLatBounds();
  (function walk(coords) {
    if (typeof coords[0] === "number") bounds.extend(coords);
    else coords.forEach(walk);
  })(geometry.coordinates);
  map.fitBounds(bounds, { padding: 40, maxZoom: 18, duration: 0 });

  map.on("load", () => {
    if (config.geometry) {
      map.addSource("parcel", { type: "geojson", data: config.geometry });
      map.addLayer({
        id: "parcel-fill",
        type: "fill",
        source: "parcel",
        paint: { "fill-color": "#facc15", "fill-opacity": 0.15 },
      });
      map.addLayer({
        id: "parcel-line",
        type: "line",
        source: "parcel",
        paint: { "line-color": "#facc15", "line-width": 3 },
      });
    }
    if (config.pin) {
      new maplibregl.Marker({ color: "#047857" }).setLngLat(config.pin.coordinates).addTo(map);
    }
  });
})();
