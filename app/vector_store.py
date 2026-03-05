import logging
import os

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

COLLECTION_NAME = "failure_messages"


def _get_client() -> chromadb.HttpClient:
    host = os.getenv("CHROMA_HOST", "chromadb")
    port = int(os.getenv("CHROMA_PORT", 8000))
    return chromadb.HttpClient(host=host, port=port)


def _get_collection():
    client = _get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=DefaultEmbeddingFunction(),
    )


def embed_failures(suite_id: int, test_cases: list[dict]) -> None:
    """Upsert failure messages for a test suite into the ChromaDB collection."""
    ids = []
    documents = []
    metadatas = []

    for tc in test_cases:
        fm = tc.get("failure_message")
        if not fm:
            continue
        ids.append(f"tc-{tc['test_case_id']}")
        documents.append(fm)
        metadatas.append(
            {
                "suite_id": suite_id,
                "test_case_id": tc["test_case_id"],
                "name": tc["name"],
            }
        )

    if ids:
        collection = _get_collection()
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)


def search_failures(query: str, n_results: int = 5) -> list[dict]:
    """Query the ChromaDB collection for similar failure messages."""
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, count),
    )

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    output = []
    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for i in range(len(ids)):
        output.append(
            {
                "test_case_id": int(metadatas[i]["test_case_id"]),
                "suite_id": int(metadatas[i]["suite_id"]),
                "name": metadatas[i]["name"],
                "failure_message": documents[i],
                "distance": float(distances[i]),
            }
        )

    output.sort(key=lambda x: x["distance"])
    return output
