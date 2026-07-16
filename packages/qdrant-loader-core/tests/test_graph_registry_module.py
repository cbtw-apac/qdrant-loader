import importlib
import sys

from qdrant_loader_core.graph.extractor.base_extractor import EntityExtractor


def test_registry_module_registers_all_builtin_extractors():
    module_name = "qdrant_loader_core.graph.registry"
    previous_registry = EntityExtractor._registry.copy()
    previous_module = sys.modules.pop(module_name, None)
    EntityExtractor._registry.clear()
    try:
        importlib.import_module(module_name)
        assert set(EntityExtractor._registry) == {
            "jira",
            "confluence",
            "git",
            "localfile",
            "publicdocs",
        }
    finally:
        EntityExtractor._registry.clear()
        EntityExtractor._registry.update(previous_registry)
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
