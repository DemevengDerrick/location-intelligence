from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

from apps.core.views import health
from apps.pages.sitemaps import PublicPagesSitemap
from apps.pages.views import robots_txt
from apps.pricing.views import set_currency

# Language-neutral endpoints: health checks, language/currency switching, SEO files, and
# (later) the JSON API and payment webhooks.
urlpatterns = [
    path("health/", health, name="health"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("currency/", set_currency, name="set_currency"),
    path("robots.txt", robots_txt, name="robots_txt"),
    path("webhooks/", include("apps.payments.webhook_urls")),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": {"pages": PublicPagesSitemap}},
        name="django.contrib.sitemaps.views.sitemap",
    ),
]

# Every user-facing page lives under /fr/... or /en/... (FR-2). A request to "/" is
# redirected by LocaleMiddleware using the language cookie, then Accept-Language.
urlpatterns += i18n_patterns(
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path(_("order/"), include("apps.orders.intake_urls")),
    path(_("my-account/"), include("apps.orders.portal_urls")),
    path("", include("apps.payments.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.pages.urls")),
    prefix_default_language=True,
)
