from typing import List, Optional
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from db.qdrant_client import qdrant_manager
from config.settings import settings
from utils.logging import retrieval_logger as logger

from qdrant_client.models import Filter, FieldCondition, MatchValue

# Import flashrank
try:
    from flashrank import Ranker, RerankRequest
    import os
    from pathlib import Path
    
    # Use a local cache directory to avoid Windows /tmp issues
    cache_dir = Path(__file__).parent.parent / ".cache" / "flashrank"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        ranker = Ranker(cache_dir=str(cache_dir)) # Loads default fast model
    except Exception as e:
        logger.error(f"Failed to initialize Ranker (OOM/Download error): {e}")
        ranker = None
except ImportError:
    logger.warning("flashrank not installed. Reranking will be disabled.")
    ranker = None

class QdrantHybridRetriever(BaseRetriever):
    k: int = 20 # Initial vector search K
    final_k: int = 4 # Final K after reranking
    threshold: float = 0.7
    tenant_id: str = "default_tenant"
    thread_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    debug_mode: bool = True
    last_trace: dict = {}
    
    def _get_relevant_documents(self, query: str, *, run_manager=None) -> List[Document]:
        try:
            self.last_trace = {
                "dense_results": [],
                "sparse_results": [],
                "fusion_results": [],
                "rerank_results": [],
                "selected_results": []
            }
            
            must_conditions = [
                FieldCondition(key="tenant_id", match=MatchValue(value=self.tenant_id))
            ]
            
            if self.thread_id:
                must_conditions.append(FieldCondition(key="thread_id", match=MatchValue(value=self.thread_id)))
            
            if self.document_ids:
                from qdrant_client.models import MatchAny
                must_conditions.append(FieldCondition(key="document_id", match=MatchAny(any=self.document_ids)))
                
            query_filter = Filter(must=must_conditions)
            
            qdrant_manager.load_models()
            
            # If debug mode, run dense and sparse separately just for tracing
            if settings.DEBUG_RETRIEVAL:
                try:
                    # dense only
                    dense_hits = qdrant_manager.client.query(
                        collection_name=qdrant_manager.collection_name,
                        query_text=query,
                        query_filter=query_filter,
                        limit=self.k,
                        using=qdrant_manager.client.get_vector_field_name()
                    )
                    self.last_trace["dense_results"] = [
                        {"score": h.score, "preview": h.document[:100], "id": h.metadata.get("id")} for h in dense_hits
                    ]
                    
                    # sparse only
                    sparse_hits = qdrant_manager.client.query(
                        collection_name=qdrant_manager.collection_name,
                        query_text=query,
                        query_filter=query_filter,
                        limit=self.k,
                        using=qdrant_manager.client.get_sparse_vector_field_name()
                    )
                    self.last_trace["sparse_results"] = [
                        {"score": h.score, "preview": h.document[:100], "id": h.metadata.get("id")} for h in sparse_hits
                    ]
                except Exception as e:
                    logger.warning(f"Failed to run debug separate queries: {e}")

            # Actual Hybrid Query (Fusion)
            results = qdrant_manager.client.query(
                collection_name=qdrant_manager.collection_name,
                query_text=query,
                query_filter=query_filter,
                limit=self.k
            )
            
            self.last_trace["fusion_results"] = [
                {"score": h.score, "preview": h.document[:100], "id": h.metadata.get("id")} for h in results
            ]
            
            # Convert Qdrant results to Langchain Documents
            docs = []
            passages = []
            for i, hit in enumerate(results):
                metadata = hit.metadata if hit.metadata else {}
                metadata["vector_score"] = hit.score
                doc = Document(page_content=hit.document, metadata=metadata)
                docs.append(doc)
                passages.append({
                    "id": i,
                    "text": hit.document,
                    "meta": metadata
                })
            
            logger.info(f"Retrieved {len(docs)} documents from Qdrant.")
            
            if not ranker or not passages:
                return docs[:self.final_k]
                
            # Rerank Phase
            final_docs = []
            rerank_trace = []
            try:
                req = RerankRequest(query=query, passages=passages)
                reranked_results = ranker.rerank(req)
                logger.info(f"--- RERANKING RESULTS for query '{query}' ---")
                
                for rank_item in reranked_results:
                    score = float(rank_item.get("score", 0.0))
                    original_index = rank_item["id"]
                    original_doc = docs[original_index]
                    
                    rerank_trace.append({
                        "score": score, 
                        "preview": original_doc.page_content[:100], 
                        "id": original_doc.metadata.get("id")
                    })
                    
                    if score >= self.threshold:
                        original_doc.metadata["rerank_score"] = score
                        final_docs.append(original_doc)
                    
                    if len(final_docs) >= self.final_k:
                        break
                        
                self.last_trace["rerank_results"] = rerank_trace
            except Exception as e:
                logger.error(f"FlashRank reranking failed: {e}")
                return docs[:self.final_k]
                
            # If threshold was too strict and we got nothing, fallback to top 1
            if not final_docs and reranked_results:
                logger.warning(f"No documents passed threshold {self.threshold}. Falling back to top 1.")
                best_idx = reranked_results[0]["id"]
                docs[best_idx].metadata["rerank_score"] = float(reranked_results[0].get("score", 0.0))
                final_docs.append(docs[best_idx])
                
            # --- CONTEXT ORDERING FIX ---
            # Group by document, keeping highest ranked document first, then restore natural order within document
            if final_docs:
                doc_groups = {}
                doc_order = []
                for doc in final_docs:
                    doc_id = doc.metadata.get("document_id", "unknown_doc")
                    if doc_id not in doc_groups:
                        doc_groups[doc_id] = []
                        doc_order.append(doc_id)
                    doc_groups[doc_id].append(doc)
                
                ordered_final_docs = []
                for doc_id in doc_order:
                    group = doc_groups[doc_id]
                    # Sort internally by page_number or id (assuming id implies sequential chunking if page not present)
                    group.sort(key=lambda x: (x.metadata.get("page_number", 0), x.metadata.get("id", "")))
                    ordered_final_docs.extend(group)
                    
                final_docs = ordered_final_docs

            self.last_trace["selected_results"] = [
                {"score": d.metadata.get("rerank_score", 0.0), "preview": d.page_content[:100], "id": d.metadata.get("id")} for d in final_docs
            ]
            
            logger.info(f"--- Returning {len(final_docs)} final grouped chunks ---")
            return final_docs
            
        except Exception as e:
            logger.error(f"Error querying Qdrant: {e}")
            return []

class RetrieverBuilder:
    def __init__(self):
        logger.info("Qdrant Retriever Builder initialized.")
        
    def build_hybrid_retriever(self, tenant_id: str = "default_tenant", thread_id: str = None, document_ids: List[str] = None, docs=None):
        """Build a hybrid retriever using Qdrant."""
        return QdrantHybridRetriever(
            k=settings.VECTOR_SEARCH_K, 
            final_k=settings.RERANKER_TOP_K,
            threshold=settings.RERANKER_THRESHOLD,
            tenant_id=tenant_id, 
            thread_id=thread_id, 
            document_ids=document_ids
        )