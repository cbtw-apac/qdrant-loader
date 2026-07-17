"""Unit tests for qdrant_loader_core.sparse.bm25."""

import math

import pytest
from qdrant_loader_core.sparse.bm25 import (
    BM25SparseEncoder,
    SparseVectorData,
    get_sparse_encoder,
)


def test_sparse_vector_data_is_empty_and_frozen() -> None:
    assert SparseVectorData(indices=[], values=[]).is_empty() is True
    assert SparseVectorData(indices=[1], values=[1.0]).is_empty() is False

    vec = SparseVectorData(indices=[1], values=[1.0])
    with pytest.raises((AttributeError, TypeError)):
        vec.indices = [2]  # type: ignore[misc]


@pytest.mark.parametrize(
    "model,expected_k1",
    [
        ("bm25", 1.2),
        ("custom", 1.2),
        ("bm25_lite", 0.9),
        ("bm25-lite", 0.9),
        ("BM25_LITE", 0.9),
    ],
)
def test_encoder_model_and_k1(model: str, expected_k1: float) -> None:
    enc = BM25SparseEncoder(model=model)
    assert enc.k1 == expected_k1


def test_encoder_normalization_and_limits() -> None:
    assert BM25SparseEncoder(model="  BM25  ").model == "bm25"
    assert BM25SparseEncoder(hash_mod=1).hash_mod == 10_000
    assert BM25SparseEncoder(hash_mod=500_000).hash_mod == 500_000


@pytest.mark.parametrize(
    "text,stop_words,expected_tokens",
    [
        ("", None, []),
        ("Hello World", set(), ["hello", "world"]),
        ("the quick brown fox", None, ["quick", "brown", "fox"]),
        ("a b c go", set(), ["go"]),
        ("hello, world! foo.", set(), ["hello", "world", "foo"]),
        ("snake_case", set(), ["snake_case"]),
        ("version 42 release", set(), ["version", "42", "release"]),
    ],
)
def test_tokenize(
    text: str, stop_words: set[str] | None, expected_tokens: list[str]
) -> None:
    enc = BM25SparseEncoder(stop_words=stop_words)
    assert enc._tokenize(text) == expected_tokens


def test_stop_words_default_and_custom() -> None:
    default_enc = BM25SparseEncoder()
    assert "the" in default_enc.stop_words

    custom = BM25SparseEncoder(stop_words={"FOO", " Bar "})
    assert custom.stop_words == frozenset({"foo", "bar"})
    assert "the" not in custom.stop_words


def test_token_to_index_is_stable_and_in_bounds() -> None:
    enc = BM25SparseEncoder(hash_mod=100_000)
    idx = enc._token_to_index("hello")
    assert 1 <= idx <= 100_000
    assert idx == enc._token_to_index("hello")


def test_token_to_index_has_reasonable_diversity() -> None:
    enc = BM25SparseEncoder()
    indices = {enc._token_to_index(f"token_{i}") for i in range(100)}
    assert len(indices) > 90


def test_encode_document_empty_and_stop_words() -> None:
    enc = BM25SparseEncoder()
    assert enc.encode_document("").is_empty()
    assert enc.encode_document("the and is with").is_empty()


def test_encode_document_weights_and_shape() -> None:
    enc = BM25SparseEncoder(stop_words=set())
    result = enc.encode_document("one two three one two one")

    assert result.indices == sorted(result.indices)
    assert len(result.indices) == len(result.values)
    assert all(v > 0 for v in result.values)


def test_encode_document_repeated_tokens_increase_weight() -> None:
    enc = BM25SparseEncoder(stop_words=set())
    single = enc.encode_document("hello")
    repeated = enc.encode_document("hello hello hello")
    assert repeated.values[0] > single.values[0]


def test_encode_document_bm25_formula() -> None:
    enc = BM25SparseEncoder(stop_words=set())
    tf = 3.0
    expected = (tf * (enc.k1 + 1.0)) / (tf + enc.k1)

    result = enc.encode_document("hello hello hello")
    hello_idx = enc._token_to_index("hello")
    pos = result.indices.index(hello_idx)
    assert abs(result.values[pos] - expected) < 1e-9


def test_encode_document_hash_collisions_merge_weights() -> None:
    enc = BM25SparseEncoder(hash_mod=10_000, stop_words=set())
    text = " ".join(f"word{i}" for i in range(200))
    result = enc.encode_document(text)

    assert len(result.indices) <= 200
    assert len(result.indices) == len(set(result.indices))


def test_encode_query_empty() -> None:
    enc = BM25SparseEncoder()
    assert enc.encode_query("").is_empty()


def test_encode_query_formula_and_difference_from_doc_mode() -> None:
    enc = BM25SparseEncoder(stop_words=set())

    query = enc.encode_query("hello hello hello")
    hello_idx = enc._token_to_index("hello")
    pos = query.indices.index(hello_idx)
    assert abs(query.values[pos] - (1.0 + math.log(3.0))) < 1e-9

    tf1 = enc.encode_query("hello")
    assert abs(tf1.values[0] - 1.0) < 1e-9

    doc = enc.encode_document("hello hello")
    qry = enc.encode_query("hello hello")
    assert doc.values != qry.values
    assert qry.indices == sorted(qry.indices)


@pytest.mark.parametrize("variant", ["bm25", "BM25", " bm25 ", "Bm25", None])
def test_get_sparse_encoder_normalizes_equivalent_names(variant: str | None) -> None:
    canonical = get_sparse_encoder("bm25")
    current = get_sparse_encoder(variant)  # type: ignore[arg-type]
    assert current is canonical
    assert current.model == "bm25"


def test_get_sparse_encoder_different_models_get_different_instances() -> None:
    a = get_sparse_encoder("bm25")
    b = get_sparse_encoder("bm25_lite")
    assert a is not b
