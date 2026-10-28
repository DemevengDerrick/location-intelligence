// Admin map of incidents (FR-35): filters by type, status and dates; click to open one.
document.addEventListener("DOMContentLoaded", () => {
  const config = JSON.parse(document.getElementById("incident-map-config").textContent);
  const labels = JSON.parse(document.getElementById("incident-map-labels").textContent);
  const form = document.getElementById("incident-filters");
  const count = document.getElementById("incident-count");
  const colours = {
    title_cancellation: "#0072B2", expropriation: "#D55E00", demolition: "#E69F00",
    double_sale: "#CC79A7", boundary_dispute: "#009E73", customary_conflict: "#56B4E9",
    public_land: "#F0E442", other: "#999999",
  };
  const map = new maplibregl.Map({
    container: "incident-map",
    style: {
      version: 8,
      sources: { basemap: { type: "raster", tiles: [config.basemapUrl], tileSize: 256, attribution: "Esri" } },
      layers: [{ id: "basemap", type: "raster", source: "basemap" }],
    },
    center: [12.35, 5.7],
    zoom: 5.3,
  });
  map.addControl(new maplibregl.NavigationControl());

  const colourExpression = ["match", ["get", "type_key"]];
  for (const [key, colour] of Object.entries(colours)) colourExpression.push(key, colour);
  colourExpression.push("#999999");

  async function load() {
    const params = new URLSearchParams(new FormData(form));
    const response = await fetch(`${config.dataUrl}?${params}`, { credentials: "same-origin" });
    const data = await response.json();
    const n = data.features.length;
    count.textContent = `${n} ${n === 1 ? labels.one : labels.count}`;
    if (map.getSource("incidents")) {
      map.getSource("incidents").setData(data);
      return;
    }
    map.addSource("incidents", { type: "geojson", data });
    map.addLayer({
      id: "incidents",
      type: "circle",
      source: "incidents",
      paint: {
        "circle-radius": 6,
        "circle-color": colourExpression,
        "circle-stroke-color": ["case", ["get", "official"], "#000000", "#FFFFFF"],
        "circle-stroke-width": ["case", ["get", "official"], 2.5, 1.2],
      },
    });
    map.on("mouseenter", "incidents", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "incidents", () => { map.getCanvas().style.cursor = ""; });
    map.on("click", "incidents", (event) => {
      const p = event.features[0].properties;
      const box = document.createElement("div");
      box.className = "incident-popup";
      const add = (text, bold) => {
        const line = document.createElement("p");
        line.textContent = text;
        if (bold) line.style.fontWeight = "600";
        box.appendChild(line);
      };
      add(`${p.type}${p.official ? ` · ${labels.official}` : ""}`, true);
      add(`${p.date || "–"} · ${p.place || "–"} (${p.precision}) · ${p.status}`);
      add(p.summary);
      const link = document.createElement("a");
      link.href = config.changeUrl.replace("/0/", `/${p.id}/`);
      link.textContent = labels.open;
      box.appendChild(link);
      new maplibregl.Popup().setLngLat(event.lngLat).setDOMContent(box).addTo(map);
    });
  }
  map.on("load", load);
  form.addEventListener("change", load);
});
