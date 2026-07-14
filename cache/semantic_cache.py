import uuid
from typing import Optional
from db.qdrant_client import qdrant_manager
from utils.logging import cache_logger as logger
from qdrant_client import models

class SemanticCache:
    def __init__(self, threshold: float = 0.95):
        self.threshold = threshold
        self.client = qdrant_manager.client
        self.collection_name = qdrant_manager.semantic_cache_name

    def _build_filter(self, tenant_id: str, thread_id: str, version: str = "0") -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=tenant_id)
                ),
                models.FieldCondition(
                    key="thread_id",
                    match=models.MatchValue(value=thread_id)
                ),
                models.FieldCondition(
                    key="version",
                    match=models.MatchValue(value=version)
                )
            ]
        )

    def check_cache(self, query: str, tenant_id: str, thread_id: str, version: str = "0") -> Optional[str]:
        try:
            qdrant_manager.load_models()
            
            # Embed manually using the dense model to avoid hybrid search RRF normalization
            model = self.client._get_or_init_model(self.client.embedding_model_name)
            vector = list(model.query_embed(query))[0]
            vector_name = self.client.get_vector_field_name()

            results = self.client.query_points(
                collection_name=self.collection_name,
                query=list(vector),
                using=vector_name,
                query_filter=self._build_filter(tenant_id, thread_id, version),
                limit=1
            )
            
            if results.points and results.points[0].score >= self.threshold:
                # Need to also verify it matches the version, but since we recreate keys per version, 
                # old versions might still exist if we didn't filter them. Wait! 
                # Qdrant queries by vector similarity, so it might return an old version!
                # We should add version to the filter!
                logger.info(f"Semantic Cache HIT! Score: {results.points[0].score:.3f}")
                return results.points[0].payload.get("answer")
            
            return None
        except Exception as e:
            logger.warning(f"Semantic cache search failed: {e}")
            return None

    def set_cache(self, query: str, answer: str, tenant_id: str, thread_id: str, version: str = "0", metadata: dict = None):
        try:
            # Generate a deterministic UUID based on query + tenant_id + thread_id + version
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant_id}:{thread_id}:v{version}:{query}"))
            qdrant_manager.load_models()
            
            payload = {"answer": answer, "tenant_id": tenant_id, "thread_id": thread_id, "version": version, "document": query}
            if metadata:
                payload.update(metadata)
                
            # Embed manually using the dense model to avoid FastEmbed sparse config validation
            model = self.client._get_or_init_model(self.client.embedding_model_name)
            vector = list(model.query_embed(query))[0]
            vector_name = self.client.get_vector_field_name()
            
            point = models.PointStruct(
                id=point_id,
                vector={vector_name: list(vector)},
                payload=payload
            )
                
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            logger.info("Saved verified answer to Semantic Cache.")
        except Exception as e:
            logger.exception(f"Failed to set semantic cache: {e}")

semantic_cache_manager = SemanticCache()
