import pytest
import os
import sys

# Add the project root to the sys path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.workflow import AgentWorkflow
from langchain_core.documents import Document

class MockRetriever:
    def invoke(self, query):
        return [Document(page_content="Hybrid search combines dense vector retrieval with keyword BM25 retrieval.", metadata={"source": "mock"})]

def test_pipeline_integration():
    workflow = AgentWorkflow()
    retriever = MockRetriever()
    
    events = list(workflow.full_pipeline(
        question="How does it work?",
        chat_history="User: What is Hybrid Search?\nAssistant: It is a retrieval method.",
        retriever=retriever
    ))
    
    final_state = events[-1]["state"]
    
    # Assert planner detected need for retrieval
    assert final_state["planner_decision"]["needs_retrieval"] == True
    
    # Assert query was rewritten
    assert final_state["current_query"] != "How does it work?"
    assert "Hybrid Search" in final_state["current_query"]
    
    # Assert documents were retrieved
    assert len(final_state["documents"]) > 0
    
    # Note: Reranking and Relevance checking will run and might assign low scores if the mock text doesn't perfectly match
    # but we can at least assert the keys exist
    assert "confidence_score" in final_state
