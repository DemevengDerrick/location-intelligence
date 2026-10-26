from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class PublicPagesSitemap(Sitemap):
    """Every public page in both languages, with hreflang alternates (FR-5)."""

    i18n = True
    alternates = True
    # Django builds x-default without the language prefix, which 404s with
    # prefix_default_language=True. Pages declare x-default in their <head> instead.
    x_default = False
    changefreq = "monthly"

    def items(self):
        return [
            "home",
            "how_it_works",
            "pricing",
            "samples",
            "faq",
            "contact",
            "about",
            "terms",
            "privacy",
            "disclaimer",
        ]

    def location(self, item):
        return reverse(f"pages:{item}")

    def priority(self, item):
        return 1.0 if item in ("home", "pricing") else 0.5
