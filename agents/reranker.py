import logging
from typing import List
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from utils.llm_factory import get_llm
from config.settings import settings
import json

logger = logging.getLogger(__name__)

class RerankedResult(BaseModel):
    top_indices: List[int] = Field(description="The indices (0 to N-1) of the most relevant chunks, ordered from most relevant to least.")

class RerankerAgent:
    def __init__(self):
        self.model = get_llm(
            temperature=0.0,
            max_tokens=250
        ).with_structured_output(RerankedResult, method="function_calling")
        
    def rerank(self, query: str, documents: List[Document], top_k: int = settings.RERANKER_TOP_K) -> List[Document]:
        if not documents:
            return []
            
        if len(documents) <= top_k:
            return documents
            
        logger.info(f"Reranking {len(documents)} chunks for query: '{query}'")
        
        # Format documents for the prompt
        docs_text = ""
        for i, doc in enumerate(documents):
            docs_text += f"\n--- Chunk {i} ---\n{doc.page_content}\n"
            
        prompt = f"""
        You are an expert search reranker.
        Your task is to identify the {top_k} most relevant chunks of text to answer the user's query.
        
        **Query:** {query}
        
        **Chunks:**
        {docs_text}
        
        **Instructions:**
        1. Evaluate how well each chunk answers or provides context for the query.
        2. If the query asks to compare or discuss multiple distinct concepts (e.g., A vs B), you MUST select a diverse set of chunks that cover ALL concepts mentioned. Diversity and coverage of all entities is more important than just matching one entity strongly.
        3. Select the indices of the top {top_k} most relevant chunks.
        4. Order them from most relevant to least relevant.
        """
        
        try:
            result = self.model.invoke(prompt)
            indices = result.top_indices
            
            # Ensure valid indices
            valid_indices = [idx for idx in indices if 0 <= idx < len(documents)]
            
            # If the model didn't return enough, append remaining top ones based on original retrieval order
            if len(valid_indices) < top_k:
                for idx in range(len(documents)):
                    if idx not in valid_indices:
                        valid_indices.append(idx)
                    if len(valid_indices) == top_k:
                        break
                        
            # Select the documents
            reranked_docs = [documents[idx] for idx in valid_indices[:top_k]]
            logger.info(f"Reranking successful. Selected indices: {valid_indices[:top_k]}")
            return reranked_docs
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}. Falling back to original order.")
            return documents[:top_k]
