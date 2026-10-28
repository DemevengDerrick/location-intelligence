import pytest
from django.contrib.sites.models import Site

pytestmark = pytest.mark.django_db


def test_sitemap_lists_both_languages_with_alternates(client):
    xml = client.get("/sitemap.xml").content.decode()
    base = f"http://{Site.objects.get_current().domain}"
    assert f"<loc>{base}/fr/tarifs/</loc>" in xml
    assert f"<loc>{base}/en/pricing/</loc>" in xml
    assert f'hreflang="en" href="{base}/en/pricing/"' in xml
    assert "/avertissement/" not in xml.replace("/fr/avertissement/", "")


def test_robots_txt_points_to_sitemap_and_hides_private_areas(client):
    body = client.get("/robots.txt").content.decode()
    assert "Sitemap: http://testserver/sitemap.xml" in body
    assert "Disallow: /fr/admin/" in body
    assert "Disallow: /en/accounts/" in body


def test_pages_have_meta_hreflang_and_open_graph(client):
    html = client.get("/fr/tarifs/").content.decode()
    assert '<link rel="alternate" hreflang="en" href="http://testserver/en/pricing/">' in html
    assert (
        '<meta property="og:image" content="http://testserver/static/img/og-default.png">' in html
    )
    assert '<meta property="og:locale" content="fr_FR">' in html
    assert 'name="description" content="Prix fixes' in html
