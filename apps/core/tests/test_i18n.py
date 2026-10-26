from pathlib import Path

import polib
import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("accept, expected", [("en-CA,en;q=0.9", "/en/"), ("fr-FR,fr", "/fr/")])
def test_root_redirects_by_browser_language(client, accept, expected):
    response = client.get("/", HTTP_ACCEPT_LANGUAGE=accept)
    assert response.status_code == 302
    assert response.url == expected


def test_language_choice_persists_over_browser_language(client):
    response = client.post("/i18n/setlang/", {"language": "en", "next": "/fr/"})
    assert response.status_code == 302
    assert response.url == "/en/"
    assert client.cookies[settings.LANGUAGE_COOKIE_NAME].value == "en"

    response = client.get("/", HTTP_ACCEPT_LANGUAGE="fr")
    assert response.url == "/en/"


@pytest.mark.parametrize(
    "path, text",
    [("/fr/", "Connaissez le terrain avant de l"), ("/en/", "Know the land before you buy it")],
)
def test_home_renders_in_each_language(client, path, text):
    response = client.get(path)
    assert response.status_code == 200
    assert text in response.content.decode()


@pytest.mark.parametrize("language", [code for code, _ in settings.LANGUAGES])
def test_translation_catalogue_is_complete(language):
    path = Path(settings.BASE_DIR) / "locale" / language / "LC_MESSAGES" / "django.po"
    po = polib.pofile(str(path))
    assert not po.metadata_is_fuzzy, "header is fuzzy, so msgfmt would skip the catalogue"

    def missing(entry):
        if entry.msgid_plural:  # every plural form must be filled
            return not entry.msgstr_plural or not all(entry.msgstr_plural.values())
        return not entry.msgstr

    untranslated = [e.msgid for e in po if not e.obsolete and (missing(e) or e.fuzzy)]
    assert untranslated == []
