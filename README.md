# Land Due-Diligence Report Platform

A bilingual (FR/EN) Django + GeoDjango platform that sells reviewed physical and environmental due-diligence reports on land parcels in Cameroon. The requirements are in [`input/land-due-diligence-trd.md`](input/land-due-diligence-trd.md).

**Status:** Phases 1 and 2 are done. Phase 3 (analysis modules) is in progress: location, current imagery, buildings, change over time, flood and water, terrain, access and services, demographics and area growth, and regulatory red flags are done, with analyst review, bilingual PDF reports with verification, and an interactive report page in the portal with shareable links. Phase 4 (staff tools: order queue, boundary editor, site-plan georeferencing, review with maps) is done. Phase 5 (area signals: news collection, per-order area search, LLM extraction, geocoding, incident review and the report section; and the optional *suggest wording* button) is built; LLM extraction and suggestions stay off until `ANTHROPIC_API_KEY` is set.

## Stack

Django 5.2 with GeoDjango · PostgreSQL 16 + PostGIS 3 · Celery + Redis (django-celery-beat) · django-allauth · Django REST Framework · HTMX + Alpine.js + Tailwind (standalone CLI) · django-storages (S3/R2) · django-anymail · Babel · uv.

## Layout

```
config/           settings (base/dev/test/prod), urls, celery
apps/             one Django app per domain:
  core            audit log, site settings, datasets/licences, health check
  accounts        custom User (email login, language, currency), Organization, roles
  orders          Order (FR-18 statuses), Attachment, Message
  parcels         Parcel (MultiPolygon 4326), geometry history, UTM area helpers
  payments        Payment (idempotent provider refs), DiscountCode
  analysis        AnalysisRun, ModuleResult
  reports         Report, ReportVersion (hash, approval)
  incidents       Source, SourceItem, Incident (FR/EN summary), IncidentSource
  gazetteer       GazetteerPlace, ReferenceLayer
  partners        Partner, FieldJob, FieldObservation
  pricing         Product (tiers/add-ons), per-currency prices, currency switcher, money formatting
  pages           public site: editable pages, FAQ, sample reports, leads, sitemap, robots.txt
  osm             local copy of the Cameroon OpenStreetMap extract (roads, services, water)
  buildings       local copy of Google Open Buildings v3 footprints for Cameroon
templates/        site layout, partials, public pages, emails, allauth layout override
assets/           Tailwind source (compiled to static/css/app.css)
static/           vendored htmx and Alpine, images, built CSS
locale/           fr and en catalogues (both always complete)
docker/           Dockerfile (dev and prod targets), entrypoint
```

## Local setup

The whole stack runs in Docker, so you don't install GDAL on the host.

```sh
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Web app | http://localhost:8000 (redirects to `/fr/` or `/en/`) |
| Mailpit (outgoing email) | http://localhost:8025 |
| S3Mock (local S3 for the private bucket) | http://localhost:9090 |
| Health check | http://localhost:8000/health/ |
| Valhalla (routing) | http://localhost:8002/status |

The `web` container applies migrations and compiles translations on start. To create an admin user:

```sh
docker compose exec web python manage.py createsuperuser
```

Then sign in at http://localhost:8000/fr/admin/. To give the user the admin role, add them to the `admin` group.

Load Cameroon's administrative boundaries once (country, regions, departments, communes from geoBoundaries). The order form needs them to check that a parcel is in Cameroon and to prefill its region and commune:

```sh
docker compose exec web python manage.py load_boundaries
```

Load the OpenStreetMap extract (about 225 MB from Geofabrik, then 10–20 minutes to import). Water, roads and services are then read from the database instead of the busy public Overpass servers, and Valhalla builds its routing tiles from the same file:

```sh
docker compose exec worker python manage.py load_osm
docker compose up -d valhalla   # first start builds the routing tiles (several minutes)
```

Load the population and built-up data once (about 3 GB; an interrupted load can simply be re-run):

```sh
docker compose exec web python manage.py load_worldpop   # WorldPop R2025A age-sex 2015–2030, Global1 totals 2000–2010
docker compose exec web python manage.py load_ghsl       # GHSL tiles for Cameroon: built-up 1975–2020, population 2000–2030
docker compose exec web python manage.py load_flood      # JRC 1-in-100-year river flood depth tiles covering Cameroon
```

Load the building footprints once (Google Open Buildings v3: six tiles, about 6.6 GB to download, then roughly an hour to keep the buildings inside Cameroon and load them). The buildings module needs it and reports "unavailable" until it is loaded. A re-run loads a new release beside the current one and switches over when complete:

```sh
docker compose exec worker python manage.py load_buildings
```

Load the quartiers, villages and lieux-dits from the OSM extract into the gazetteer (about 13,000 places, a minute). Area signals use them to search the parcel's own quartier first and to locate news about a neighbourhood. Re-run after an OSM refresh; aliases added by analysts are kept:

```sh
docker compose exec web python manage.py load_places
```

Load the official protected areas, permanent forest estate and concessions from the [Forest Atlas of Cameroon](https://cmr-data.forest-atlas.org/) (MINFOF with WRI; about 1,200 features, a minute). It reads each layer from the atlas's public feature service; `--file` loads a local export of one layer instead. Re-running a layer replaces it:

```sh
docker compose exec web python manage.py load_forest_atlas
docker compose exec web python manage.py load_forest_atlas protected_areas --file "input/Aires_protege_de_la_faune/Aires_protegées_de_la_faune.shp"
```

The extract is refreshed every Sunday at 02:00 (Celery beat, editable under Periodic tasks; also **OSM imports → Download and load the latest extract now** in the admin). A refresh loads beside the current data and switches over only when complete. To rebuild the routing tiles after a refresh: `docker compose run --rm -e force_rebuild=True valhalla`.

### Order form

The form at `/fr/commande/` (`/en/order/`) has five steps: location, details, report, account, review. Progress is saved after each step. The location step offers:
- a map pin, which is analysed as a 30 m circle and flagged "approximate";
- a boundary drawn on Esri World Imagery;
- an uploaded file: KML, KMZ, GeoJSON, GPX, zipped shapefile, or CSV in lon/lat or UTM 32N/33N;
- a photo or PDF of the site plan, for the analyst to georeference.

Place search checks the gazetteer first, then OSM Nominatim. Nominatim is called from the server, cached, and limited to 1 request per second, per its usage policy. Set `NOMINATIM_USER_AGENT` to a real contact address. Production imagery needs `ESRI_API_KEY` (ArcGIS Location Platform).

The checks are editable in the admin under Core → Settings → `parcel_intake`: the minimum and maximum area warnings, the pin buffer radius, and the threshold for flagging a stated vs computed area difference.

### Content you edit in the admin

- **Prices:** Pricing → Products. There is one price per tier per currency (XAF, CAD, EUR, USD). Prices are set by hand, not converted live. The desk report launches at 10,000 XAF.
- **Pages:** Public site → Pages (About, Terms, Privacy, Disclaimer), with French and English tabs. Terms, Privacy and Disclaimer are seeded as drafts marked *pending legal review*. Untick that box once a lawyer has approved the text.
- **FAQ and sample reports:** Public site → FAQ / Sample reports. Upload one PDF per language.
- **WhatsApp button:** Core → Settings → `whatsapp_number`, in international format (e.g. `237600000000`). The button stays hidden while the number is empty.
- **Leads** from the contact form appear under Public site → Leads and are emailed to `ADMIN_NOTIFICATION_EMAILS`.

### Payments

After the review step, the customer pays at `/fr/payer/<order>/` (`/en/pay/<order>/`). Rules:
- An order becomes *Paid* **only** from a verified provider webhook or an admin action, never from the browser coming back from checkout (FR-14).
- Webhooks are signature-checked, stored once per event (`WebhookEvent`) and safe to replay.
- After payment, the order moves to *Processing*, or to *Needs georeferencing* for site-plan-only orders. A receipt is emailed in the customer's language.

| Mode | Card | Mobile money |
| --- | --- | --- |
| `PAYMENTS_DEMO_MODE=True` (dev, sales demos) | Demo checkout | Demo checkout (XAF) |
| Demo off, `STRIPE_SECRET_KEY` set | Stripe Checkout | Not offered until an aggregator is integrated |

In demo mode the demo checkout page has Approve and Decline buttons and sends a *signed* webhook through the same code path a real provider uses. No money moves.

To test Stripe locally:
1. Set `PAYMENTS_DEMO_MODE=False` and put your `sk_test_…` key in `STRIPE_SECRET_KEY`.
2. Run `stripe listen --forward-to localhost:8000/webhooks/stripe/`.
3. Copy the `whsec_…` it prints into `STRIPE_WEBHOOK_SECRET`.

In the admin, restricted to the **admin** role:
- Orders → action **Mark as paid (bank transfer)**.
- Payments → action **Refund the selected payment**. Stripe refunds go through Stripe; other refunds are recorded only.
- Discount codes: percentage or fixed amount, with expiry and usage limit. A code is counted as used only when its payment succeeds.

Add a mobile-money aggregator by writing another `PaymentProvider` (`apps/payments/providers/`) and returning it from `checkout_provider()`.

### Customer portal

Signed-in customers land on **My orders** at `/fr/mon-compte/` (`/en/my-account/`). It lists their orders with status badges and links to any unfinished order. Each order page shows:
- the report area (a placeholder until reports exist), the parcel map and details, and their files (served through signed links);
- a message thread with the analyst, and the progress timeline;
- payments, and an **Add field verification** upgrade where the customer pays only the price difference.

Analysts reply from the order's page in the admin. The customer is emailed, and customer messages are emailed to `ADMIN_NOTIFICATION_EMAILS`.

Every status change emails the customer in their own language. The payment steps are covered by the receipt, so paying sends one email, not three. Customers set their name, phone, language and currency under **My details**.

### Analysis and reports

1. **Analysis.** When an order is paid (and has a boundary), the worker runs one task per module and stores each result separately. A failed module shows as "unavailable" and never blocks the others. The modules so far:

   | Module | Data | Rating (thresholds in Core → Settings → `analysis_thresholds`) |
   | --- | --- | --- |
   | Location | Parcel geometry, geoBoundaries | Stated vs computed area difference; grey for pin-only parcels |
   | Terrain | Copernicus DEM GLO-30, read as a small window over HTTP | Mean slope; share of the parcel over the erosion slope |
   | Buildings | Google Open Buildings v3 (local copy; detections below the `building_min_confidence` threshold, 0.7, are ignored) | On the parcel → red; within 20 m → amber |
   | Current imagery | Sentinel-2 L2A from AWS Earth Search: cloud-masked median of the last 12 months | Mostly not vegetated → amber (never red: pixels can't tell buildings from bare soil) |
   | Change over time | Sentinel-2 dry-season (Dec–Feb) composites, one per year since 2017 | Vegetation lost in the last 5 years → amber |
   | Access and services | Local OSM copy (roads, schools, health facilities, markets, water points), Valhalla routing | No road within 500 m → red; parcel not on a road, paved road over 2 km, health facility over 30 min by car or school over 30 min on foot → amber |
   | Demographics and growth | WorldPop R2025A age-sex rasters (2015, 2020, 2025, 2030 projected) for 1 km, 5 km and the commune, plus growth per 5-year period since 2000 compared with GHSL population (GHS-POP), shown as rates only: WorldPop 2000–2010 is the older Global1 release, and no rate spans the two releases; GHSL built-up epochs | Annual growth within 5 km: 2 % or more → green; 0–2 % → amber; falling → red |
   | Regulatory red flags | Setback rules (Core → Settings → `setback_rules`) around OSM watercourses, water bodies, shore, main roads, railways and power lines; Forest Atlas protected areas, forest estate and concessions (OSM protected areas only until those are loaded); uploaded official layers | Gazetted protected area (other than a Ramsar wetland), permanent forest estate or DUP zone on the parcel, or setbacks over 10 % of it → red; any other constraint on or within 200 m (including proposed areas and concessions) → amber |
   | Flood and water | Copernicus EMS/JRC 1-in-100-year river flood depth (local tiles), JRC Global Surface Water (1984–2021), OSM rivers, water bodies and wetlands | 10 % of the parcel in the flood zone, any part 1 m deep or more, water seen on 10 % of it, or a wetland on it → red; any part in the flood zone, the zone within 200 m, or water seen on it → amber |
   | Area signals | Approved land-issue incidents from Cameroonian outlets' feeds and the GDELT news index (see *Area signals* below) | Not rated: "for information" (blue *i*), since these are area-level reports, not findings about the parcel |

2. **Findings.** Each module's finding is a sentence from **Analysis → Finding templates** (French and English, with placeholders like `{area}`), filled with computed numbers. Findings are never written by an LLM.

3. **Review.** When all modules have finished, the order moves to *In review*. In the admin, go to **Reports → Open review** to see each finding beside its interactive map (the same layers as the customer's report page). There you can edit the wording in both languages, override a rating (a reason is required), hide a section (a reason is required) and add a note. Then click **Approve and deliver**. **Re-run this module** runs one module again and rebuilds only its finding, keeping your edits to the others; **Re-run analysis** starts over and replaces the draft. A delivered report can be reopened; it is approved as a new version and earlier versions are kept.

4. **Approval.** Approving renders A4 PDFs in French and English with WeasyPrint. Each page carries the report ID and a QR code that links to `/fr/verifier/<report-id>/`. That public page confirms a PDF is genuine and unaltered by comparing its SHA-256 with the stored one. The customer gets an email, and the summary and both PDFs appear on their order page.

5. **Interactive report.** Delivered reports open at `/fr/mon-compte/commandes/<id>/rapport/` (`/en/my-account/orders/<id>/report/`), from the order page. The page shows the latest approved version (with the analyst's edits) in the reader's language: summary tiles, every section with a MapLibre map of its layers (toggles, legends, hover readouts, a swipe between imagery years for change over time), interactive Vega-Lite charts from the same specs as the PDF with a data table under each, and the PDFs. Each module stores its layers on `ModuleResult.layers` (`apps/analysis/layers.py`); image layers are PNGs in the private bucket served through short-lived signed URLs. Maps start only when scrolled into view.

6. **Share links.** The owner can create read-only links valid 7, 30 or 90 days (`REPORT_SHARE_DAYS`), copy and revoke them on the report page. A shared page shows the report and PDFs only (no messages, payments or account data), is marked `noindex` and sends no referrer. Creating, viewing and revoking links are written to the audit log.

**Re-running:** to analyse an order again, use Orders → action **Run the analysis** (for orders that are processing or in review).

### Staff tools (Phase 4)

- **Order queue** (Orders): filters for service level, status, tier, region, the customer's deadline and age since payment. The *due* column shows the service-level target, in red when it has passed. Targets are business days (Monday to Friday, public holidays not counted) per tier in Core → Settings → `service_levels` (`{"desk": 3}`; a tier without a number is never flagged).
- **Order page**: under the usual fields, the status of each analysis module (with errors), the audit log for the order, its parcel, payments and report, and links to the boundary editor and the review.
- **Boundary editor** (order page → *Edit the boundary*, or Parcels → *Open the editor*): draw or edit the boundary over Esri imagery with snapping, or type corner coordinates (WGS 84 or UTM 32N/33N). Saving validates the shape like the order form, keeps the previous boundary in the history (dashed yellow on the map), sets the input method to *Digitized by analyst*, writes the audit log and re-runs the whole analysis. A delivered order goes back through review and gets a new version. A run that a newer boundary has superseded never touches the draft.
- **Site-plan georeferencing** (same page, for orders with a plan): pick the plan (image or PDF, first page), click a point on the plan then the same point on the map, at least 3 times. The plan is fitted with an affine transform by least squares in UTM and overlaid with adjustable opacity; with 4 or more points each point's error in metres and the RMSE show a misplaced point. Then trace the boundary on top. The control points are saved on the attachment. Orders that were *Needs georeferencing* start processing when the boundary is saved.

**Land cover** has three classes: vegetation, water, and "built-up or bare ground". At 10 m, Sentinel-2 cannot reliably separate roofs from cleared laterite, so whether a parcel is built on comes from the Buildings section.

**Earth Search offset quirk:** for scenes processed since 2022, Earth Search's band metadata lists an offset of −0.1, but the stored values are already corrected (`earthsearch:boa_offset_applied`). Applying the offset again makes recent scenes far too dark and creates fake vegetation trends. See `reflectance_params()`.

**Flood and water** overlays the parcel on the JRC 1-in-100-year river flood depth (~90 m, resampled to the 30 m surface-water grid). That model covers flooding from rivers with large catchments only, not flooding from heavy rain, blocked drains or the sea, and every green or amber finding says so. Rivers and water bodies (natural water only: OSM drains and ditches are left out, since in Douala they line most streets) are drawn for context and give the distance to the nearest water, which does not change the rating. The flood tiles are read from disk once `load_flood` has run (over HTTP until then); surface water is read as small windows over HTTP.

**Access**: times start where Valhalla joins the road network nearest the parcel centre, plus the walk from the parcel to that road (4.5 km/h). For each service the 5 nearest (straight line) are routed and the quickest kept. Without a surface tag, only motorways, trunk and primary roads count as paved. "On a road" means a mapped road within 10 m of the boundary; it does not prove a legal right of way.

**Demographics** describe the people around the parcel, not on it. Totals are the sum of the WorldPop age-sex bands, so the pyramid always adds up to the total. Figures are cached per area, release and year (`PopulationStat`), so each commune is computed once. They are modelled estimates, not census counts, and the report says so.

**Red flags**: setback rules are a list in Core → Settings → `setback_rules` (category, OSM kinds, distance in metres, FR/EN label, legal basis, `confirmed`). The seeded river (25 m) and sea-shore (50 m) public-domain widths follow Ordonnance n° 74-2 of 1974; the road, railway and power-line widths are indicative. Every rule stays `confirmed: false`, shown with an asterisk in reports, until a Cameroonian lawyer has checked it. Upload public-utility (DUP) zones, infrastructure corridors, national protected areas and risk zones under **Gazetteer → Reference layers → Import a layer** (GeoJSON, KML or zipped shapefile; a `buffer_m` or `width_m` attribute widens lines into corridors). WDPA is not used: its licence excludes commercial use.

**Forest Atlas layers** (`load_forest_atlas`, `apps/gazetteer/forest_atlas.py`):

| Layer | Kind | On the parcel |
| --- | --- | --- |
| `protected_areas`: national parks, wildlife reserves and sanctuaries | Protected area | Red; amber if only proposed |
| `forest_reserves`: protection, recreation and research forests, reforestation perimeters | Permanent forest estate | Red; amber if classification is under way |
| `production_forests`: forest management units (UFA) and council forests | Permanent forest estate | Red; amber if not yet classified |
| `plantations`: agro-industrial plantations (CDC, SOCAPALM, HEVECAM…) | Concession | Amber |
| `community_forests` | Concession | Amber |
| `hunting_zones`: hunting and community hunting zones | Concession | Amber |
| `ramsar_sites`: the 7 Ramsar wetlands of international importance | Protected area (advisory) | Amber |

Once any protected area is loaded as a reference layer, OSM protected areas are no longer checked. The atlas's annual cutting areas, timber sales, planted zones, protected-area zoning and administrative boundaries are not loaded: they add nothing a land buyer needs beyond the layers above. Its licence is not stated on the portal; it is a public government open-data site, and reports credit MINFOF and WRI.

**Report order:** the cover says who the report was prepared for (name, organisation, intended use; never email or phone, since reports can be shared). After the summary, the location and boundary check sets the scene, then the most telling analysis leads: demographics, access, flood and terrain, red flags, then imagery and buildings, change over time, field findings and area signals last (`apps/reports/structure.py`). In the PDF, the paired maps of demographics, access and flood sit side by side, and map source lines wrap to the map's width. The summary tiles and the review screen follow the same order, including for drafts made before a change of order.

**Network errors** (busy public servers, timeouts, 429/5xx) make a module retry after 1 and then 2 minutes before it is recorded as unavailable. Other errors are recorded at once.

**PDF maps** use Sentinel-2 imagery (open licence, attributed) for current imagery and change. The other maps are vector maps; Esri imagery stays web-only until its print licensing is settled. Whether Esri imagery may be printed in paid reports is an open licensing question.

### Area signals (Phase 5)

Reported land issues near the parcel (TRD §5), from a reviewed incident database:

1. **Collection.** Every day at 03:30 (Periodic tasks → *Collect land-issue news*) the outlets in **Incidents → Sources** are read through their RSS feeds, plus a national GDELT search. Only land-related items are kept (Core → Settings → `area_signals`, French and English): a strong keyword anywhere (litige foncier, déguerpissement, expropriation, land dispute…), or a weak one (foncier, chefferie, lotissement…) in the title, or two different weak ones in the text, so stories that mention land only in passing stay out. Starter outlets: Journal du Cameroun, Actu Cameroun, Mimi Mefo Info, Data Cameroon, Le Bled Parle, Cameroon News Agency, 237actu, Journal Intégration, Investir au Cameroun and The Post. A feed with a repeated XML attribute (a common WordPress plugin bug) is repaired before parsing. Every fetch checks the site's robots.txt first; no social networks or login pages. The text of an item (title and feed description) stays private and is never shown to customers. Analysts can add an item by URL or by uploading a PDF notice (**Source items → Add by URL or PDF**).
2. **Area search for each order.** The signals module searches the parcel's area, widening step by step: the nearest quartier or village (within 1.5 km; a landmark lieu-dit only when there is none), the commune, the department, then the region (admin 1). It stops at the first level where at least `min_items` (5) relevant items have been found. Each search, per place and provider (outlets' own search feeds, and GDELT), is saved in **Area searches** and reused by later orders in the same place for `max_age_days` (30). Failed searches are saved too and tried again on the next order. English-language outlets are searched with English words (`outlet_search_words_en`: land, eviction, demolition). GDELT allows one request every 5 seconds; after a 429 it is left alone for 10 minutes and the outlets carry on. **GDELT is off by default** since October 2026: its free DOC API refused about half the requests from our server and returned no articles even for "Douala" or "Cameroon". Set `"gdelt_enabled": true` in `area_signals` to try it again; the per-order search and the daily national search then use it.
3. **Extraction.** With `ANTHROPIC_API_KEY` set, each new item goes to Claude (`LLM_MODEL`, default `claude-opus-5-5`), which returns zero or more incidents: type (FR-27), place names, event date, a neutral summary of at most 40 words in French and English with no private individuals named, an official-act flag and a confidence score. Without a key nothing is sent anywhere: the action **Create an incident by hand from the item** opens a blank incident placed at the area searched.
4. **Geocoding.** Place names are matched against the gazetteer (names and aliases, ignoring case and accents). When several places share a name, the one inside a commune or department the article also names wins. Unknown names go to **Unmatched place names**; mapping one to a place adds it as an alias and locates its incidents again. The geoBoundaries communes now carry the spellings the press uses ("Douala 5e" for Douala V), regions their French names, and Wouri and Mfoundi the city names.
5. **Review.** New incidents are *unreviewed* and never reach a report. In **Incidents**, the *Approve* action shows the summaries once more and asks the analyst to confirm that no private individual is named (FR-31). Analysts can also reject, merge duplicates (the oldest keeps every source) and mark official acts. **Map of incidents** shows them all, filterable by type, status and dates (FR-35).
6. **In the report.** The section lists approved incidents from the last 10 years: quartier and point incidents within 2 km, and commune, department or region incidents for the levels searched, official acts first and then newest first. Each entry has its date, type, place and precision, the summary and a link to the source. The section always carries the statement that these are public reports about the area, not findings about the parcel. On the review screen, the signals finding says how many incidents are waiting for review, so the analyst can approve them and re-run the module before delivery.

This widening search is a deliberate change to FR-29, which kept incidents above commune level out of reports: they are now shown, labelled with their level ("In the region"). GDELT's free API only looks back three months; older history comes from the outlets' search feeds and from items analysts add by hand.

**Suggest wording (FR-43).** With `ANTHROPIC_API_KEY` set, each finding on the review screen gets a *Suggest clearer wording* button. Claude proposes a plainer version that keeps every number, place and caveat; nothing changes until the analyst clicks *Use this wording*, and the analyst still saves the draft.

### Roles

The four groups `customer`, `analyst`, `partner` and `admin` are created and given their base permissions after every `migrate`. Self-registered users (email or Google) become customers. Use `apps.accounts.permissions.role_required` on views and `HasRole` on DRF views. A customer's access to their own orders is checked object by object.

## Tests and checks

```sh
docker compose exec web pytest
docker compose exec web ruff check .
docker compose exec web ruff format --check .
docker compose exec web python manage.py makemigrations --check --dry-run
```

CI (`.github/workflows/ci.yml`) runs the same checks against PostGIS and Redis service containers.

## Translations

Every user-facing string lives in `locale/{fr,en}/LC_MESSAGES/django.po`, and both catalogues must be complete. A test fails on any missing or fuzzy entry. URL paths are translated too (`/fr/tarifs/` and `/en/pricing/`). After adding strings:

```sh
docker compose exec web python manage.py makemessages -l fr -l en --ignore=.venv --ignore=input --no-obsolete
# translate the new entries in both files, then:
docker compose exec web python manage.py compilemessages --ignore=.venv
```

Bilingual database content (pages, FAQ, products, incident summaries) uses django-modeltranslation, which adds `_fr` and `_en` columns.

## Celery

`worker` and `beat` run from the same image. Scheduled tasks are stored in the database through django-celery-beat. Smoke test:

```sh
docker compose exec web python manage.py shell -c "from apps.core.tasks import ping; print(ping.delay().get(timeout=10))"
```

## Running the pipeline on a sample parcel

Coming in Phase 3.

## Deployment (outline)

The `prod` Dockerfile target builds minified CSS, compiles messages, collects static files and runs Gunicorn as a non-root user. The planned topology is one VPS running Docker Compose with Nginx (TLS), Gunicorn, a Celery worker, Celery beat, Postgres/PostGIS and Redis, plus daily off-site database backups. Set `DJANGO_SETTINGS_MODULE=config.settings.prod` and provide every variable in `.env.example`, using real R2, email provider and Sentry credentials. The full deployment guide arrives with Phase 7 (Hardening).
