"""Publish a sample report on the public site from a real analysis of an example parcel.

    manage.py make_sample_report --lon 9.74 --lat 4.08 --side 30 --quartier Bonamoussadi \\
        --commune "Douala V" --region Littoral --title-fr "..." --title-en "..."
    manage.py make_sample_report --order 5 --title-fr "..." --title-en "..."

The first form creates an order for a square parcel and runs every module in this process
(a few minutes); the second reuses the draft of an existing order. Both render the French and
English PDFs as samples (the requester is replaced by "Sample client") and publish them.
"""

from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import User
from apps.analysis import pipeline
from apps.orders.models import Order, OrderStatus
from apps.pages.models import SampleReport
from apps.parcels.models import InputMethod, Parcel
from apps.parcels.testing import square_m
from apps.reports.pdf import render_pdf

SAMPLE_CUSTOMER = "samples@example.invalid"


def sample_order(lon, lat, side, **place):
    customer, _created = User.objects.get_or_create(
        email=SAMPLE_CUSTOMER,
        defaults={"first_name": "Sample", "last_name": "client", "is_active": False},
    )
    order = Order.objects.create(
        customer=customer,
        tier="desk",
        price_amount=Decimal(0),
        status=OrderStatus.PROCESSING,
        notes="Sample report for the public site",
    )
    Parcel.objects.create(
        order=order,
        geometry=square_m(lon, lat, side),
        input_method=InputMethod.DRAWN,
        **place,
    )
    return order


def run_analysis(order):
    """Every module, one after the other, in this process; builds the draft at the end."""
    with transaction.atomic():
        runs = pipeline.start_runs(order)
    for run in runs:
        for result in run.module_results.all():
            pipeline.execute_module(result.pk)
    order.refresh_from_db()
    return order.report


def summary(draft, place, language):
    """ "Bonamoussadi, Douala V: 2 warnings, 1 point to check, 6 good." in that language."""
    counts = {}
    for finding in draft["findings"]:
        if not finding.get("hidden"):
            counts[finding["rating"]] = counts.get(finding["rating"], 0) + 1
    with translation.override(language):
        parts = [
            ngettext("%(n)s warning", "%(n)s warnings", counts.get("red", 0)),
            ngettext("%(n)s point to check", "%(n)s points to check", counts.get("amber", 0)),
            ngettext("%(n)s good", "%(n)s good", counts.get("green", 0)),
        ]
        numbers = [counts.get("red", 0), counts.get("amber", 0), counts.get("green", 0)]
        listed = ", ".join(p % {"n": n} for p, n in zip(parts, numbers, strict=True) if n)
        return _("%(place)s: %(findings)s.") % {"place": place, "findings": listed}


class Command(BaseCommand):
    help = "Publish a sample report from a real analysis of an example parcel"

    def add_arguments(self, parser):
        parser.add_argument("--order", type=int, help="Reuse this order's report draft")
        parser.add_argument("--lon", type=float)
        parser.add_argument("--lat", type=float)
        parser.add_argument("--side", type=float, default=30, help="Side of the square (m)")
        parser.add_argument("--quartier", default="")
        parser.add_argument("--commune", default="")
        parser.add_argument("--region", default="")
        parser.add_argument("--title-fr", required=True)
        parser.add_argument("--title-en", required=True)
        parser.add_argument("--sort-order", type=int, default=0)

    def handle(self, *args, **options):
        if options["order"]:
            order = Order.objects.filter(pk=options["order"]).first()
            report = getattr(order, "report", None)
            if report is None or not report.draft:
                raise CommandError("That order has no report draft.")
        else:
            if options["lon"] is None or options["lat"] is None:
                raise CommandError("Give --order, or --lon and --lat.")
            place = {k: options[k] for k in ("quartier", "commune", "region")}
            order = sample_order(options["lon"], options["lat"], options["side"], **place)
            self.stdout.write(f"Running the analysis for order {order.pk}…")
            report = run_analysis(order)
        parcel = order.parcels.first()
        place = ", ".join(p for p in (parcel.quartier, parcel.commune) if p) or "–"
        sample = SampleReport(
            title_fr=options["title_fr"],
            title_en=options["title_en"],
            summary_fr=summary(report.draft, place, "fr"),
            summary_en=summary(report.draft, place, "en"),
            sort_order=options["sort_order"],
            is_published=True,
        )
        for language in ("fr", "en"):
            pdf = render_pdf(report, report.draft, language, 1, sample=True)
            getattr(sample, f"pdf_{language}").save(
                f"sample-{report.reference}-{language}.pdf", ContentFile(pdf), save=False
            )
        sample.save()
        self.stdout.write(f"Published sample {sample.pk}: {sample.title_en} ({sample.summary_en})")
