"""Registry of analysis modules, in report order. Phase 3 adds the remaining modules here."""

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
        LocationModule(),
        ImageryModule(),
        BuildingsModule(),
        ChangeModule(),
        FloodModule(),
        TerrainModule(),
        AccessModule(),
        DemographicsModule(),
        RedFlagsModule(),
    )
}

__all__ = ["MODULES", "Module", "ModuleOutput"]
