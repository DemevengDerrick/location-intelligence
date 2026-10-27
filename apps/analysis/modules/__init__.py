"""Registry of analysis modules, in report order (see apps.reports.structure.SECTIONS)."""

from .access import AccessModule
from .base import Module, ModuleOutput
from .buildings import BuildingsModule
from .change import ChangeModule
from .demographics import DemographicsModule
from .flood import FloodModule
from .imagery import ImageryModule
from .location import LocationModule
from .red_flags import RedFlagsModule
from .terrain import TerrainModule

MODULES: dict[str, Module] = {
    m.name: m
    for m in (
        DemographicsModule(),
        AccessModule(),
        FloodModule(),
        TerrainModule(),
        RedFlagsModule(),
        ImageryModule(),
        BuildingsModule(),
        ChangeModule(),
        LocationModule(),
    )
}

__all__ = ["MODULES", "Module", "ModuleOutput"]
