"""Starter outlets (feeds checked against robots.txt on 2026-10-27), area-signals settings and
the daily collection at 03:30 (editable under Periodic tasks)."""

from django.db import migrations

SOURCES = [
    # name, feed, search feed ("" when robots.txt or the site refuses searches), language
    ("Journal du Cameroun", "https://www.journalducameroun.com/feed/",
     "https://www.journalducameroun.com/?s={query}&feed=rss2", "fr"),
    ("Actu Cameroun", "https://actucameroun.com/feed/", "", "fr"),
    ("Mimi Mefo Info", "https://mimimefoinfos.com/feed/", "", "fr"),
    ("Data Cameroon", "https://datacameroon.com/feed/",
     "https://datacameroon.com/?s={query}&feed=rss2", "fr"),
    ("Le Bled Parle", "https://www.lebledparle.com/feed/",
     "https://www.lebledparle.com/?s={query}&feed=rss2", "fr"),
    ("Cameroon News Agency", "https://cameroonnewsagency.com/feed/",
     "https://cameroonnewsagency.com/?s={query}&feed=rss2", "en"),
]  # fmt: skip
TASK = "apps.incidents.tasks.collect_sources"


def seed(apps, schema_editor):
    from apps.incidents.config import SETTING_KEY, SignalsSettings

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
    defaults = SignalsSettings()
    apps.get_model("core", "SiteSetting").objects.get_or_create(
        key=SETTING_KEY,
        defaults={
            "value": {
                "radius_km": defaults.radius_km,
                "years": defaults.years,
                "max_age_days": defaults.max_age_days,
                "min_items": defaults.min_items,
            },
            "description": "Area signals: search radius, years listed, how long a place's "
            "saved news search is reused, and the item count below which the search widens "
            "to the next admin level. Keyword lists can be added as 'keywords', "
            "'gdelt_keywords' and 'outlet_search_words'.",
        },
    )
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="30", hour="3", day_of_week="*", day_of_month="*", month_of_year="*",
        timezone="Africa/Douala",
    )  # fmt: skip
    PeriodicTask.objects.update_or_create(
        name="Collect land-issue news", defaults={"task": TASK, "crontab": crontab}
    )


def unseed(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(task=TASK).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("incidents", "0002_incident_place_source_search_url_and_more"),
        ("core", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
