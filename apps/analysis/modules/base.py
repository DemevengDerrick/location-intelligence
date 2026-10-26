"""Contract every analysis module follows (TRD §4, "Rules for every module")."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.utils import translation

from ..models import ModuleStatus, Rating


@dataclass
class ModuleOutput:
    status: str = ModuleStatus.OK  # ok, warning or failed
    rating: str = Rating.GREY
    results: dict = field(default_factory=dict)  # numbers stored for reproducibility
    parameters: dict = field(default_factory=dict)  # thresholds and settings used
    datasets: dict = field(default_factory=dict)  # dataset slug -> version
    maps: dict = field(default_factory=dict)  # map name -> {language: SVG bytes}
    # chart name -> {language: Vega-Lite spec}, or {"reason": {language: text}} when the
    # chart cannot be drawn (shown as a labelled placeholder, FR-68)
    charts: dict = field(default_factory=dict)


class Module(ABC):
    name: str  # stable identifier, stored on ModuleResult
    title = ""  # lazily translated section title

    @abstractmethod
    def run(self, parcel) -> ModuleOutput:
        """Analyse the parcel. Raise on unrecoverable errors; the pipeline records them."""

    def finding_values(self, results) -> dict:
        """Placeholder values for this module's finding templates."""
        return dict(results)

    def key_figure(self, results) -> str:
        """The one number shown on the summary tile, in the active language."""
        return ""

    @staticmethod
    def per_language(build):
        """Call `build()` once per language (translated labels); returns {lang: value}."""
        values = {}
        for language in ("fr", "en"):
            with translation.override(language):
                values[language] = build()
        return values

    # Maps are drawn once per language so legends and source lines are translated.
    render_maps = per_language
