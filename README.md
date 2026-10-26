# Land Due-Diligence Report Platform

A bilingual (FR/EN) Django + GeoDjango platform that sells reviewed physical and environmental due-diligence reports on land parcels in Cameroon. The requirements are in [`input/land-due-diligence-trd.md`](input/land-due-diligence-trd.md).

**Status:** Phases 1 and 2 are done. Phase 3 (analysis modules) is in progress: location, current imagery, buildings, change over time, flood and water, terrain, access and services, demographics and area growth, and regulatory red flags are done, with analyst review, bilingual PDF reports with verification, and delivery to the portal. The interactive report page in the portal (3g) and area signals come next.

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
  osm             local copy of the Cameroon OpenStreetMap extract (roads, services, buildings, water)
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

Load the OpenStreetMap extract (about 225 MB from Geofabrik, then 10–20 minutes to import). Buildings, water, roads and services are then read from the database instead of the busy public Overpass servers, and Valhalla builds its routing tiles from the same file:

```sh
docker compose exec worker python manage.py load_osm
docker compose up -d valhalla   # first start builds the routing tiles (several minutes)
```

Load the population and built-up data once (about 3 GB; an interrupted load can simply be re-run):

```sh
docker compose exec web python manage.py load_worldpop   # WorldPop R2025A age-sex rasters, 2020/2025/2030
docker compose exec web python manage.py load_ghsl       # GHSL built-up tiles for Cameroon, 1975–2020
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
   | Buildings | OpenStreetMap via Overpass (`OVERPASS_URL`, comma-separated servers, with retries) | On the parcel → red; within 20 m → amber |
   | Current imagery | Sentinel-2 L2A from AWS Earth Search: cloud-masked median of the last 12 months | Mostly not vegetated → amber (never red: pixels can't tell buildings from bare soil) |
   | Change over time | Sentinel-2 dry-season (Dec–Feb) composites, one per year since 2017 | Vegetation lost in the last 5 years → amber |
   | Access and services | Local OSM copy (roads, schools, health facilities, markets, water points), Valhalla routing | No road within 500 m → red; parcel not on a road, paved road over 2 km, health facility over 30 min by car or school over 30 min on foot → amber |
   | Demographics and growth | WorldPop R2025A age-sex rasters (2020, 2025, 2030 projected) for 1 km, 5 km and the commune; GHSL built-up epochs | Annual growth within 5 km: 2 % or more → green; 0–2 % → amber; falling → red |
   | Regulatory red flags | Setback rules (Core → Settings → `setback_rules`) around OSM watercourses, water bodies, shore, main roads, railways and power lines; OSM protected areas; uploaded official layers | Protected area or DUP zone on the parcel, or setbacks over 10 % of it → red; any other constraint on or within 200 m → amber |
   | Flood and water | JRC Global Surface Water (1984–2021), Copernicus EMS/JRC 1-in-100-year river flood maps, OSM rivers, water bodies and wetlands, height above nearest water from the DEM | Water seen on, flood zone on, or wetland on the parcel → red; nearby water, nearby flood zone or low height above water → amber |

2. **Findings.** Each module's finding is a sentence from **Analysis → Finding templates** (French and English, with placeholders like `{area}`), filled with computed numbers. Findings are never written by an LLM.

3. **Review.** When all modules have finished, the order moves to *In review*. In the admin, go to **Reports → Open review** to see each finding beside its map. There you can edit the wording in both languages, override a rating (a reason is required), hide a section (a reason is required) and add a note. Then click **Approve and deliver**. You can also re-run the analysis there, or reopen a delivered report. A reopened report is approved as a new version; earlier versions are kept.

4. **Approval.** Approving renders A4 PDFs in French and English with WeasyPrint. Each page carries the report ID and a QR code that links to `/fr/verifier/<report-id>/`. That public page confirms a PDF is genuine and unaltered by comparing its SHA-256 with the stored one. The customer gets an email, and the summary and both PDFs appear on their order page.

**Re-running:** to analyse an order again, use Orders → action **Run the analysis** (for orders that are processing or in review).

**Land cover** has three classes: vegetation, water, and "built-up or bare ground". At 10 m, Sentinel-2 cannot reliably separate roofs from cleared laterite, so whether a parcel is built on comes from the Buildings section.

**Earth Search offset quirk:** for scenes processed since 2022, Earth Search's band metadata lists an offset of −0.1, but the stored values are already corrected (`earthsearch:boa_offset_applied`). Applying the offset again makes recent scenes far too dark and creates fake vegetation trends. See `reflectance_params()`.

**Flood and water** counts natural water only (rivers, streams, canals, water bodies, wetlands, observed surface water). OSM drains and ditches are left out: in Douala they line most streets. The height above water comes from a surface model (rooftops included), so it can only make a parcel amber, never red. Global datasets are read as small windows over HTTP; the list of flood-map tiles is cached for 30 days.

**Access**: times start where Valhalla joins the road network nearest the parcel centre, plus the walk from the parcel to that road (4.5 km/h). For each service the 5 nearest (straight line) are routed and the quickest kept. Without a surface tag, only motorways, trunk and primary roads count as paved. "On a road" means a mapped road within 10 m of the boundary; it does not prove a legal right of way.

**Demographics** describe the people around the parcel, not on it. Totals are the sum of the WorldPop age-sex bands, so the pyramid always adds up to the total. Figures are cached per area, release and year (`PopulationStat`), so each commune is computed once. They are modelled estimates, not census counts, and the report says so.

**Red flags**: setback rules are a list in Core → Settings → `setback_rules` (category, OSM kinds, distance in metres, FR/EN label, legal basis, `confirmed`). The seeded river (25 m) and sea-shore (50 m) public-domain widths follow Ordonnance n° 74-2 of 1974; the road, railway and power-line widths are indicative. Every rule stays `confirmed: false`, shown with an asterisk in reports, until a Cameroonian lawyer has checked it. Upload public-utility (DUP) zones, infrastructure corridors, national protected areas and risk zones under **Gazetteer → Reference layers → Import a layer** (GeoJSON, KML or zipped shapefile; a `buffer_m` or `width_m` attribute widens lines into corridors). WDPA is not used: its licence excludes commercial use.

**Network errors** (busy public servers, timeouts, 429/5xx) make a module retry after 1 and then 2 minutes before it is recorded as unavailable. Other errors are recorded at once.

**PDF maps** use Sentinel-2 imagery (open licence, attributed) for current imagery and change. The other maps are vector maps; Esri imagery stays web-only until its print licensing is settled. Whether Esri imagery may be printed in paid reports is an open licensing question.

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
