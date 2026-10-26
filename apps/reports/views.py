import hashlib

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django_ratelimit.decorators import ratelimit

from .models import Report, ReportVersion
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
