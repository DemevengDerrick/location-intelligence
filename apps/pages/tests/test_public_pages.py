import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import translation

from apps.core.models import SiteSetting
from apps.pages.models import Page, SampleReport

pytestmark = pytest.mark.django_db

PUBLIC_PAGES = [
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


@pytest.mark.parametrize("language", ["fr", "en"])
@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_every_public_page_renders_in_both_languages(client, name, language):
    with translation.override(language):
        url = reverse(f"pages:{name}")
    response = client.get(url)
    assert response.status_code == 200
    assert f'<html lang="{language}">' in response.content.decode()


@pytest.mark.parametrize(
    "name, fr_path, en_path",
    [
        ("pricing", "/fr/tarifs/", "/en/pricing/"),
        ("how_it_works", "/fr/comment-ca-marche/", "/en/how-it-works/"),
        ("disclaimer", "/fr/avertissement/", "/en/disclaimer/"),
    ],
)
def test_urls_are_translated(name, fr_path, en_path):
    with translation.override("fr"):
        assert reverse(f"pages:{name}") == fr_path
    with translation.override("en"):
        assert reverse(f"pages:{name}") == en_path


def test_switching_language_keeps_the_page(client):
    response = client.post("/i18n/setlang/", {"language": "en", "next": "/fr/tarifs/"})
    assert response.url == "/en/pricing/"


def test_legal_pages_are_seeded_bilingual_and_flagged_as_drafts(client):
    page = Page.objects.get(slug="disclaimer")
    assert page.is_draft
    fr = client.get("/fr/avertissement/").content.decode()
    en = client.get("/en/disclaimer/").content.decode()
    assert "ni une vérification juridique du titre foncier" in fr
    assert "not a legal title search" in en
    assert "awaiting legal review" in en


def test_admin_edits_to_a_page_appear_on_the_site(client):
    Page.objects.filter(slug="about").update(title_en="Who we are", is_draft=False)
    response = client.get("/en/about/")
    assert "Who we are" in response.content.decode()
    assert "awaiting legal review" not in response.content.decode()


def test_whatsapp_button_uses_the_admin_setting(client):
    assert "wa.me" not in client.get("/en/").content.decode()  # hidden while unset

    SiteSetting.objects.filter(key="whatsapp_number").update(value="+237 600 000 000")
    SiteSetting.objects.get(key="whatsapp_number").save()  # clears the cached value
    html = client.get("/en/").content.decode()
    assert "https://wa.me/237600000000?text=" in html


def test_sample_download_redirects_to_the_language_pdf(client):
    sample = SampleReport.objects.create(title="Douala sample", is_published=True)
    sample.pdf_fr.save("sample-fr.pdf", ContentFile(b"%PDF-1.4 fr"))
    sample.pdf_en.save("sample-en.pdf", ContentFile(b"%PDF-1.4 en"))

    response = client.get(f"/en/sample-reports/{sample.pk}/pdf/")
    assert response.status_code == 302
    assert "sample-en" in response.url


def test_unpublished_sample_is_not_downloadable(client):
    sample = SampleReport.objects.create(title="Draft", is_published=False)
    sample.pdf_fr.save("draft.pdf", ContentFile(b"%PDF-1.4"))
    assert client.get(f"/fr/exemples-de-rapports/{sample.pk}/pdf/").status_code == 404
