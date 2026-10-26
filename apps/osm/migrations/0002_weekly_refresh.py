"""Refresh the OpenStreetMap extract every Sunday at 02:00 (editable under Periodic tasks)."""

from django.db import migrations

TASK = "apps.osm.tasks.refresh_osm"


def schedule(apps, schema_editor):
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="0", hour="2", day_of_week="0", day_of_month="*", month_of_year="*",
        timezone="Africa/Douala",
    )  # fmt: skip
    PeriodicTask.objects.update_or_create(
        name="Refresh OpenStreetMap extract", defaults={"task": TASK, "crontab": crontab}
    )


def unschedule(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(task=TASK).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("osm", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(schedule, unschedule)]
