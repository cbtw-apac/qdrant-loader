from __future__ import annotations

from harborrag import CompositionRoot, HarborDocument, stable_hash_id


def test_meta_exports_public_facade():
    assert stable_hash_id("unit", "x").value.startswith("harbor://unit/")
    assert (
        CompositionRoot.local().diagnostics()["runtime"]["provider"] == "mock_runtime"
    )
    assert HarborDocument.__name__ == "HarborDocument"
