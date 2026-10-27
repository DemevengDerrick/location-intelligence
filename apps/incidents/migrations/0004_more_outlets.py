"""More outlets (feeds checked against robots.txt on 2026-10-27), Mimi Mefo Info marked as
English (the language picks the words typed into an outlet's search) and the settings help
text listing the newer options."""

from django.db import migrations

SOURCES = [
    # name, feed, search feed ("" when the site has none), language
    ("237actu", "https://www.237actu.com/feed/",
     "https://www.237actu.com/?s={query}&feed=rss2", "fr"),
    ("Journal Intégration", "https://www.journalintegration.com/?feed=rss2",
     "https://www.journalintegration.com/?s={query}&feed=rss2", "fr"),
    ("Investir au Cameroun", "https://www.investiraucameroun.com/feed/", "", "fr"),
    ("The Post", "https://www.thepostnewspaper.net/feed/",
     "https://www.thepostnewspaper.net/?s={query}&feed=rss2", "en"),
]  # fmt: skip


def seed(apps, schema_editor):
    Source = apps.get_model("incidents", "Source")
    for name, url, search_url, language in SOURCES:
        Source.objects.update_or_create(
            url=url,
            defaults={
                "name": name,
                "search_url": search_url,
                "source_type": "rss",
                "language": language,
            },
        )
    Source.objects.filter(url="https://mimimefoinfos.com/feed/").update(language="en")
    apps.get_model("core", "SiteSetting").objects.filter(key="area_signals").update(
        description="Area signals: search radius, years listed, how long a place's saved news "
        "search is reused, and the item count below which the search widens to the next admin "
        "level. Optional keys: 'keywords' (strong land words, enough anywhere), "
        "'weak_keywords' (enough in a title, or two different ones in the text), "
        "'outlet_search_words' and 'outlet_search_words_en' (typed into French and English "
        "outlets' search), 'gdelt_keywords', and 'gdelt_enabled' (false turns GDELT off)."
    )


class Migration(migrations.Migration):
    dependencies = [("incidents", "0003_seed_sources_settings_schedule"), ("core", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
