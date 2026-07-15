import sys

from qdrant_loader_core.graph.extractor.base_extractor import EntityExtractor


def test_registry_module_registers_all_builtin_extractors():
    EntityExtractor._registry.clear()
    sys.modules.pop("qdrant_loader_core.graph.registry", None)

    import qdrant_loader_core.graph.registry  # noqa: F401

    assert set(EntityExtractor._registry.keys()) == {
        "jira",
        "confluence",
        "git",
        "localfile",
        "publicdocs",
    }

    EntityExtractor._registry.clear()
