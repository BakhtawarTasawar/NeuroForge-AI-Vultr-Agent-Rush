import logging
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple
from qdrant_client import QdrantClient, models

from app.core.config import settings

logger = logging.getLogger("neuroforge.vector_store")


def _to_point_id(raw_id: str) -> str:
    """Ensure point ID is a valid RFC 4122 UUID string as required by Qdrant."""
    try:
        return str(uuid.UUID(raw_id))
    except (ValueError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id)))


class VectorStore:
    """
    Persistent, multi-tenant vector storage engine backed by Qdrant.
    Enforces strict project-level isolation on every query.
    PostgreSQL remains the primary relational database for document metadata and chunks.
    """

    def __init__(
        self,
        client: Optional[QdrantClient] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        location: Optional[str] = None,
        collection_name: Optional[str] = None,
        dimension: Optional[int] = None,
        prefer_grpc: Optional[bool] = None,
    ):
        self.collection_name = collection_name or getattr(settings, "QDRANT_COLLECTION", "scientific_knowledge")
        self.dimension = dimension or getattr(settings, "EMBEDDING_DIMENSION", 2560)
        self._lock = threading.Lock()

        if client is not None:
            self.client = client
        elif location is not None:
            self.client = QdrantClient(location=location)
        elif getattr(settings, "current_env", "") == "test":
            self.client = QdrantClient(":memory:")
        else:
            q_url = url or getattr(settings, "QDRANT_URL", None)
            q_host = host or getattr(settings, "QDRANT_HOST", "127.0.0.1")
            q_port = port or getattr(settings, "QDRANT_PORT", 6333)
            q_key = api_key or getattr(settings, "QDRANT_API_KEY", None)
            q_grpc = prefer_grpc if prefer_grpc is not None else getattr(settings, "QDRANT_PREFER_GRPC", False)

            try:
                if q_url:
                    self.client = QdrantClient(url=q_url, api_key=q_key, prefer_grpc=q_grpc, timeout=10.0)
                else:
                    self.client = QdrantClient(host=q_host, port=q_port, api_key=q_key, prefer_grpc=q_grpc, timeout=10.0)
            except Exception as exc:
                logger.warning(f"Could not connect to remote Qdrant ({exc}). Initializing local fallback store.")
                self.client = QdrantClient(":memory:")

        self._init_collection()

    def _init_collection(self) -> None:
        """Create Qdrant collection and payload indexes if not already present."""
        with self._lock:
            try:
                if not self.client.collection_exists(self.collection_name):
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=models.VectorParams(
                            size=self.dimension,
                            distance=models.Distance.COSINE,
                        ),
                    )
                    logger.info(f"Initialized Qdrant collection '{self.collection_name}' (dim={self.dimension}, distance=COSINE).")

                # Setup payload indexes for multi-tenant and document-level filtering
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    try:
                        self.client.create_payload_index(
                            collection_name=self.collection_name,
                            field_name="project_id",
                            field_schema=models.PayloadSchemaType.KEYWORD,
                        )
                        self.client.create_payload_index(
                            collection_name=self.collection_name,
                            field_name="document_id",
                            field_schema=models.PayloadSchemaType.KEYWORD,
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Failed to ensure Qdrant collection '{self.collection_name}': {e}")
                raise

    def upsert_chunks(
        self,
        chunks: List[Tuple[Any, ...]],
    ) -> None:
        """
        Upsert a batch of chunk vectors to Qdrant.
        Accepts: (chunk_id, project_id, document_id, vector_floats, [optional_payload_dict])
        """
        if not chunks:
            return

        points: List[models.PointStruct] = []
        for item in chunks:
            chunk_id = item[0]
            project_id = item[1]
            doc_id = item[2]
            vec = item[3]
            extra_payload = item[4] if len(item) > 4 and isinstance(item[4], dict) else {}

            # Validate or pad/truncate dimension
            if len(vec) != self.dimension:
                if len(vec) < self.dimension:
                    vec = vec + [0.0] * (self.dimension - len(vec))
                else:
                    vec = vec[: self.dimension]

            point_id = _to_point_id(chunk_id)
            payload = {
                "chunk_id": str(chunk_id),
                "project_id": str(project_id),
                "document_id": str(doc_id),
            }
            if extra_payload:
                payload.update(extra_payload)
            points.append(models.PointStruct(id=point_id, vector=vec, payload=payload))

        with self._lock:
            # Upload in batches of 64 points
            batch_size = 64
            for i in range(0, len(points), batch_size):
                batch = points[i : i + batch_size]
                self.client.upsert(collection_name=self.collection_name, points=batch)

    def search(
        self,
        project_id: str,
        query_vector: List[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> List[Tuple[str, float]]:
        """
        Execute semantic similarity search strictly scoped to project_id in Qdrant.
        Returns a list of (chunk_id, similarity_score) sorted by relevance descending.
        """
        if len(query_vector) != self.dimension:
            if len(query_vector) < self.dimension:
                query_vector = query_vector + [0.0] * (self.dimension - len(query_vector))
            else:
                query_vector = query_vector[: self.dimension]

        # Strict project isolation filter
        project_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="project_id",
                    match=models.MatchValue(value=str(project_id)),
                )
            ]
        )

        with self._lock:
            try:
                res = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=project_filter,
                    limit=top_k,
                    score_threshold=score_threshold if score_threshold > 0.0 else None,
                )
            except Exception as e:
                logger.error(f"Qdrant query_points failed: {e}")
                return []

        results: List[Tuple[str, float]] = []
        for pt in res.points:
            score = max(0.0, min(1.0, float(pt.score)))
            if score >= score_threshold:
                chunk_id = pt.payload.get("chunk_id", str(pt.id)) if pt.payload else str(pt.id)
                results.append((chunk_id, round(score, 4)))

        return results

    def delete_document_chunks(self, document_id: str) -> int:
        """Remove all chunk vectors associated with a document from Qdrant."""
        doc_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=str(document_id)),
                )
            ]
        )
        with self._lock:
            try:
                cnt = self.client.count(collection_name=self.collection_name, count_filter=doc_filter)
                count_to_delete = int(cnt.count)
                if count_to_delete > 0:
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=models.FilterSelector(filter=doc_filter),
                    )
                return count_to_delete
            except Exception as e:
                logger.error(f"Failed to delete document '{document_id}' points from Qdrant: {e}")
                return 0

    def delete_project_chunks(self, project_id: str) -> int:
        """Remove all chunk vectors associated with a project from Qdrant."""
        proj_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="project_id",
                    match=models.MatchValue(value=str(project_id)),
                )
            ]
        )
        with self._lock:
            try:
                cnt = self.client.count(collection_name=self.collection_name, count_filter=proj_filter)
                count_to_delete = int(cnt.count)
                if count_to_delete > 0:
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=models.FilterSelector(filter=proj_filter),
                    )
                return count_to_delete
            except Exception as e:
                logger.error(f"Failed to delete project '{project_id}' points from Qdrant: {e}")
                return 0

    def count_project_chunks(self, project_id: str) -> int:
        """Return total number of indexed vectors for a specific project in Qdrant."""
        proj_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="project_id",
                    match=models.MatchValue(value=str(project_id)),
                )
            ]
        )
        with self._lock:
            try:
                cnt = self.client.count(collection_name=self.collection_name, count_filter=proj_filter)
                return int(cnt.count)
            except Exception as e:
                logger.error(f"Failed to count project '{project_id}' points in Qdrant: {e}")
                return 0
