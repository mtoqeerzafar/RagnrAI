import sys, os, logging
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

logging.basicConfig(level=logging.WARNING, format='%(name)s | %(message)s')

from agents.workflow import AgentWorkflow
from retriever.builder import RetrieverBuilder

def test_regression():
    workflow = AgentWorkflow()
    retriever = RetrieverBuilder().build_hybrid_retriever(tenant_id="default_tenant", thread_id=None)

    history = """user: How Prompt Injection and Answer Generation works?
assistant: The process of Prompt Injection and Answer Generation works by appending retrieved chunks to the user's query in the prompt, which is then processed by a Large Language Model (LLM) to generate a response. The LLM uses the query and the retrieved chunks to generate an answer, and the system includes mechanisms for handling images and tables to provide a more comprehensive and user-friendly output."""

    queries = [
        "Can you summarize it in 3 bullet points?",
        "Can you write the equation for the process you explained earlier?",
        "What happens after that?",
        "Why do they append the retrieved chunks instead of directly asking the model?",
    ]

    for q in queries:
        print(f"\n{'='*70}")
        print(f"TESTING QUERY: {q}")
        print(f"{'='*70}")

        state_history = {}
        for event in workflow.full_pipeline(question=q, retriever=retriever, chat_history=history):
            node = event["node"]
            state = event["state"]
            state_history[node] = state
            
        final_state = state_history.get("final", {})
        
        decision = final_state.get("planner_decision", {})
        needs_retrieval = decision.get("needs_retrieval")
        
        ran_rewrite = "rewrite_query" in state_history
        ran_retrieval = "retrieve" in state_history
        
        rewritten_query = final_state.get("current_query", "")
        confidence_score = final_state.get("confidence_score", 0.0)
        docs = final_state.get("documents", [])
        
        print(f"Planner needs_retrieval: {needs_retrieval}")
        print(f"Ran Rewrite Node: {ran_rewrite}")
        print(f"Ran Retrieval Node: {ran_retrieval}")
        print(f"Rewritten Query: {rewritten_query}")
        print(f"Confidence Score: {confidence_score}")
        if docs:
            top_score = docs[0].metadata.get("rerank_score", 0)
            print(f"Top 1 Rerank Score: {top_score}")
        else:
            top_score = 0
            
        # Assertions
        try:
            assert ran_retrieval == True, "Retrieval was skipped!"
            assert "Prompt Injection" in rewritten_query or "Answer Generation" in rewritten_query or "append" in rewritten_query, f"Implicit reference not resolved correctly. Got: {rewritten_query}"
            assert top_score > 0.5, f"Top rerank score too low: {top_score}"
            assert confidence_score >= 0.75, f"Relevance score too low: {confidence_score}"
            print("✅ TEST PASSED")
        except AssertionError as e:
            print(f"❌ TEST FAILED: {e}")

if __name__ == "__main__":
    test_regression()
