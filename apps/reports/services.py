"""Analyst review and approval (FR-42, FR-44)."""

import copy
import hashlib

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.analysis.models import Rating
from apps.core.audit import log_action
from apps.orders.models import Order, OrderStatus
from apps.orders.status import transition

from .drafts import LANGUAGES
from .models import Report, ReportVersion
from .pdf import render_pdf


class ReviewError(Exception):
    """A problem with the analyst's edits, shown on the review screen."""


def apply_edits(report, data):
    """Update the draft from the review form. Raises ReviewError if a reason is missing."""
    draft = copy.deepcopy(report.draft)
    errors = []
    for i, finding in enumerate(draft["findings"]):
        rating = data.get(f"rating_{i}", finding["rating"])
        if rating not in Rating.values:
            rating = finding["rating"]
        finding["rating"] = rating
        finding["override_reason"] = data.get(f"override_reason_{i}", "").strip()
        if rating != finding["computed_rating"] and not finding["override_reason"]:
            errors.append(
                _("Give a reason for changing the rating of “%(m)s”.") % {"m": finding["module"]}
            )
        for lang in LANGUAGES:
            text = data.get(f"text_{lang}_{i}")
            if text is not None:
                finding["text"][lang] = text.strip()
        finding["hidden"] = data.get(f"hidden_{i}") == "on"
        finding["hidden_reason"] = data.get(f"hidden_reason_{i}", "").strip()
        if finding["hidden"] and not finding["hidden_reason"]:
            errors.append(_("Give a reason for hiding “%(m)s”.") % {"m": finding["module"]})
    for lang in LANGUAGES:
        draft["note"][lang] = data.get(f"note_{lang}", draft["note"][lang]).strip()
    report.draft = draft  # keep the edits on screen even when invalid
    if errors:
        raise ReviewError(" ".join(errors))
    report.save(update_fields=["draft", "updated_at"])
    return report


@transaction.atomic
def approve(report, *, analyst, request=None):
    """Lock the draft as a new version: render both PDFs, store their hashes, deliver."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    order = Order.objects.select_for_update().get(pk=report.order_id)
    if order.status != OrderStatus.IN_REVIEW:
        raise ReviewError(_("Only orders in review can be approved."))
    number = report.latest_number + 1
    content = copy.deepcopy(report.draft)
    now = timezone.now()
    for language in LANGUAGES:
        pdf = render_pdf(report, content, language, number)
        version = ReportVersion(
            report=report,
            number=number,
            language=language,
            content=content,
            sha256=hashlib.sha256(pdf).hexdigest(),
            approved_by=analyst,
            approved_at=now,
        )
        version.pdf.save(
            f"{report.reference}-v{number}-{language}.pdf", ContentFile(pdf), save=False
        )
        version.save()
    log_action(
        "report.approved", actor=analyst, target=report, request=request, data={"version": number}
    )
    transition(order, OrderStatus.DELIVERED, actor=analyst, request=request)
    return number


def reopen(report, *, analyst, request=None):
    """Changes after delivery create a new version: send the order back to review."""
    transition(report.order, OrderStatus.IN_REVIEW, actor=analyst, request=request, note="reopened")


def find_version_by_hash(report, digest):
    return report.versions.filter(sha256=digest).first()
