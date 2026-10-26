import hashlib
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.audit import log_action

from .models import Report, ReportShare, ReportVersion
from .page import latest_versions, page_context
from .services import find_version_by_hash

MAX_PDF_BYTES = 30 * 1024 * 1024


@ratelimit(key="ip", rate="30/h", method="POST", block=False)
def verify(request, reference):
    """Public page behind each report's QR code: is this PDF genuine and unaltered?

    Shows no personal data: only the report ID and its version dates.
    """
    report = get_object_or_404(Report, reference=reference)
    versions = report.versions.order_by("number", "language")
    outcome = None
    if request.method == "POST" and not getattr(request, "limited", False):
        upload = request.FILES.get("pdf")
        if upload is None or upload.size > MAX_PDF_BYTES:
            outcome = {"status": "invalid"}
        else:
            digest = hashlib.sha256()
            for chunk in upload.chunks():
                digest.update(chunk)
            match = find_version_by_hash(report, digest.hexdigest())
            outcome = {"status": "genuine", "version": match} if match else {"status": "altered"}
    return render(
        request, "reports/verify.html", {"report": report, "versions": versions, "outcome": outcome}
    )


@login_required
def download(request, public_id, number, language):
    version = get_object_or_404(
        ReportVersion,
        report__order__public_id=public_id,
        report__order__customer=request.user,
        number=number,
        language=language,
    )
    return HttpResponseRedirect(version.pdf.url)  # short-lived signed URL


# --- Interactive report page (FR-19) ---------------------------------------------------------


def _report_for(request, public_id):
    """The order's report for its owner, or for staff (analysts, admins)."""
    reports = Report.objects.select_related("order")
    if request.user.is_staff:
        return get_object_or_404(reports, order__public_id=public_id)
    return get_object_or_404(reports, order__public_id=public_id, order__customer=request.user)


@login_required
def report_page(request, public_id):
    report = _report_for(request, public_id)
    language = translation.get_language() or "fr"
    context = page_context(report, language)
    is_owner = report.order.customer_id == request.user.id
    if is_owner:
        context["shares"] = [s for s in report.shares.all() if s.is_active]
        context["share_days"] = settings.REPORT_SHARE_DAYS
        context["share_default_days"] = settings.REPORT_SHARE_DEFAULT_DAYS
    context.update({"is_owner": is_owner, "shared": None})
    return render(request, "reports/report_page.html", context)


@login_required
@require_POST
def share_create(request, public_id):
    report = get_object_or_404(Report, order__public_id=public_id, order__customer=request.user)
    latest_versions(report)  # only delivered reports can be shared
    try:
        days = int(request.POST.get("days", settings.REPORT_SHARE_DEFAULT_DAYS))
    except ValueError:
        days = settings.REPORT_SHARE_DEFAULT_DAYS
    if days not in settings.REPORT_SHARE_DAYS:
        days = settings.REPORT_SHARE_DEFAULT_DAYS
    share = ReportShare.objects.create(
        report=report, created_by=request.user, expires_at=timezone.now() + timedelta(days=days)
    )
    log_action(
        "report.share_created",
        actor=request.user,
        target=report,
        request=request,
        data={"share": share.pk, "days": days},
    )
    messages.success(request, _("Share link created. Anyone with the link can read the report."))
    return redirect(reverse("reports:page", args=[public_id]) + "#share")


@login_required
@require_POST
def share_revoke(request, public_id, pk):
    share = get_object_or_404(
        ReportShare,
        pk=pk,
        report__order__public_id=public_id,
        report__order__customer=request.user,
        revoked_at__isnull=True,
    )
    share.revoked_at = timezone.now()
    share.save(update_fields=["revoked_at", "updated_at"])
    log_action(
        "report.share_revoked",
        actor=request.user,
        target=share.report,
        request=request,
        data={"share": share.pk},
    )
    messages.success(request, _("The share link no longer works."))
    return redirect(reverse("reports:page", args=[public_id]) + "#share")


def _active_share(token):
    share = ReportShare.objects.select_related("report__order").filter(token=token).first()
    if share is None or not share.is_active:
        raise Http404("Unknown, expired or revoked link")
    return share


def shared_report(request, token):
    """A read-only report for whoever holds the link: no messages, payments or account data."""
    share = _active_share(token)
    ReportShare.objects.filter(pk=share.pk).update(
        views=F("views") + 1, last_viewed_at=timezone.now()
    )
    log_action(
        "report.share_viewed", target=share.report, request=request, data={"share": share.pk}
    )
    context = page_context(share.report, translation.get_language() or "fr")
    context.update({"is_owner": False, "shared": share})
    response = render(request, "reports/report_page.html", context)
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"  # the token must not leak to other sites
    return response


def shared_download(request, token, number, language):
    share = _active_share(token)
    version = get_object_or_404(
        ReportVersion, report=share.report, number=number, language=language
    )
    return HttpResponseRedirect(version.pdf.url)
