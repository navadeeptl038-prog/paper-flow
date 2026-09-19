import uuid

import pytest

from models.chunk import ChunkRecord
from services import embedding_service
from storage import document_repository


@pytest.fixture(autouse=True)
def reset_embedding_generator():
    original = embedding_service._test_embedding_generator
    yield
    embedding_service.set_test_embedding_generator(original)


def _fixed_embedding(value: float = 0.25) -> list[float]:
    return [value] * 384


def test_generate_embedding_returns_384_dimensions():
    embedding_service.set_test_embedding_generator(lambda text: _fixed_embedding(0.5))

    vec = embedding_service.generate_embedding("hello world")

    assert isinstance(vec, list)
    assert len(vec) == 384
    assert vec[0] == 0.5


def test_generate_embeddings_batch_returns_real_vectors():
    embedding_service.set_test_embedding_generator(lambda text: _fixed_embedding(0.1))

    vectors = embedding_service.generate_embeddings_batch(["alpha", "beta", "gamma"])

    assert len(vectors) == 3
    assert all(len(v) == 384 for v in vectors)
    assert all(v[0] == 0.1 for v in vectors)


def test_store_chunk_embedding_and_fetch_similar_result():
    owner_a = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    embedding_service.set_test_embedding_generator(lambda text: _fixed_embedding(0.25))

    chunk = ChunkRecord(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        owner_id=owner_a,
        chunk_index=0,
        content="Alpha plan for project delivery",
        page_number=1,
        embedding=_fixed_embedding(0.25),
        metadata={"source": "landing"},
    )
    document_repository.save_document_chunks([chunk], owner_id=owner_a)

    results = document_repository.search_vector_chunks(
        query_embedding=_fixed_embedding(0.25),
        owner_id=owner_a,
        top_k=5,
        threshold=0.0,
        document_id=doc_id,
    )

    assert len(results) >= 1
    assert results[0].document_id == doc_id
    assert results[0].owner_id == owner_a
    assert results[0].chunk_index == 0


def test_user_isolation_on_vector_search_and_chunk_retrieval():
    owner_a = str(uuid.uuid4())
    owner_b = str(uuid.uuid4())
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())

    embedding_service.set_test_embedding_generator(lambda text: _fixed_embedding(0.25))

    chunk_a = ChunkRecord(
        id=str(uuid.uuid4()),
        document_id=doc_a,
        owner_id=owner_a,
        chunk_index=0,
        content="Public project note for user A",
        page_number=1,
        embedding=_fixed_embedding(0.25),
    )
    chunk_b = ChunkRecord(
        id=str(uuid.uuid4()),
        document_id=doc_b,
        owner_id=owner_b,
        chunk_index=0,
        content="Top secret private note for user B",
        page_number=1,
        embedding=_fixed_embedding(0.25),
    )

    document_repository.save_document_chunks([chunk_a], owner_id=owner_a)
    document_repository.save_document_chunks([chunk_b], owner_id=owner_b)

    results = document_repository.search_vector_chunks(
        query_embedding=_fixed_embedding(0.25),
        owner_id=owner_a,
        top_k=10,
        threshold=0.0,
    )

    assert all(r.owner_id == owner_a for r in results)
    assert not any(r.document_id == doc_b for r in results)

    retrieved = document_repository.get_document_chunks_by_doc(doc_b, owner_id=owner_a)
    assert retrieved == []
