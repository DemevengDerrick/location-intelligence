"""The editable report draft: findings built from a completed run, then edited by the analyst."""

from django.utils import translation

from apps.analysis.findings import render_finding, unavailable_text
from apps.analysis.models import ModuleStatus, Rating
from apps.analysis.modules import MODULES

from .models import Report

LANGUAGES = ("fr", "en")


def _key_figure(module_name, results, language):
    with translation.override(language):
        return MODULES[module_name].key_figure(results)


def build_draft(run):
    results = {r.module: r for r in run.module_results.all()}
    findings = []
    for name in MODULES:  # report order
        result = results.get(name)
        if result is None:
            continue
        unavailable = result.status == ModuleStatus.FAILED
        rating = Rating.GREY if unavailable else result.rating
        findings.append(
            {
                "module": name,
                "computed_rating": rating,
                "rating": rating,
                "override_reason": "",
                "text": {
                    lang: unavailable_text(lang)
                    if unavailable
                    else render_finding(name, rating, result.results, lang)
                    for lang in LANGUAGES
                },
                "results": result.results,
                "key": {
                    lang: "" if unavailable else _key_figure(name, result.results, lang)
                    for lang in LANGUAGES
                },
                "charts": result.charts,
                "maps": result.maps,
                "datasets": result.dataset_versions,
                "unavailable": unavailable,
                "hidden": False,
                "hidden_reason": "",
            }
        )
    return {
        "run": run.pk,
        "approximate": run.parcel.is_approximate,
        "findings": findings,
        "note": {lang: "" for lang in LANGUAGES},
    }


def store_draft(order, run):
    """Create or refresh the order's report draft from a completed run."""
    report, _created = Report.objects.get_or_create(order=order)
    report.run = run
    report.draft = build_draft(run)
    report.save(update_fields=["run", "draft", "updated_at"])
    return report
