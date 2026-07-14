import logging
from typing import TypedDict, List, Dict
from langchain_core.messages import AIMessage
from langgraph.graph import StateGraph, END
from langchain_core.documents import Document

from .research_agent import ResearchAgent
from .verification_agent import VerificationAgent
from .relevance_checker import RelevanceChecker
from .query_rewriter import QueryRewriter
from .planner import WorkflowPlanner
from .reranker import RerankerAgent
from config.settings import settings
from utils.llm_factory import get_llm
from cache.exact_cache import exact_cache_manager
from cache.semantic_cache import semantic_cache_manager
from utils.sanitize import strip_reasoning
import asyncio
from utils.logging import workflow_logger as logger

class RetrievalTrace(TypedDict, total=False):
    raw_query: str
    standalone_query: str
    retrieval_queries: List[str]
    dense_results: List[dict]
    sparse_results: List[dict]
    fusion_results: List[dict]
    rerank_results: List[dict]
    selected_results: List[dict]
    latencies: Dict[str, float]

class AgentState(TypedDict):
    question: str
    chat_history: str
    tenant_id: str
    thread_id: str
    attachments: List[dict]
    planner_decision: dict
    current_query: str
    retrieval_queries: List[str]
    documents: List[Document]
    cached_documents: List[Document]
    draft_answer: str
    verification_report: str
    failure_reason: str
    relevance_result: dict
    retriever: object
    revision_count: int
    retrieval_attempts: int
    feedback: str
    used_cache: bool
    fallback_identical: bool
    rewrite_failed: bool
    turn_status: str
    retrieval_trace: RetrievalTrace

class AgentWorkflow:
    def __init__(self, checkpointer=None):
        self.planner = WorkflowPlanner()
        self.researcher = ResearchAgent()
        self.verifier = VerificationAgent()
        self.relevance_checker = RelevanceChecker()
        self.rewriter = QueryRewriter()
        self.reranker = RerankerAgent()
        
        self.chat_model = get_llm(
            temperature=0.7,
            max_tokens=2048,
            agent_name="chat_responder"
        )
        self.compiled_workflow = self.build_workflow(checkpointer)
        
    def build_workflow(self, checkpointer=None):
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("plan", self._plan_step)
        workflow.add_node("chat_responder", self._chat_responder_step)
        workflow.add_node("rewrite_query", self._rewrite_query_step)
        workflow.add_node("check_cache", self._check_cache_step)
        workflow.add_node("retrieve", self._retrieve_step)
        workflow.add_node("rerank", self._rerank_step)
        workflow.add_node("check_relevance", self._check_relevance_step)
        workflow.add_node("fallback_rewrite", self._fallback_rewrite_step)
        workflow.add_node("handle_irrelevant", self._handle_irrelevant_step)
        workflow.add_node("research", self._research_step)
        workflow.add_node("verify", self._verification_step)
        workflow.add_node("output_guardrail", self._output_guardrail_step)
        
        workflow.set_entry_point("plan")
        
        workflow.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "chat": "chat_responder",
                "rewrite_query": "rewrite_query"
            }
        )
        
        workflow.add_edge("chat_responder", "output_guardrail")
        
        workflow.add_conditional_edges(
            "rewrite_query",
            self._route_after_rewrite,
            {
                "check_cache": "check_cache",
                "output_guardrail": "output_guardrail"
            }
        )
        
        workflow.add_conditional_edges(
            "check_cache",
            self._route_after_cache,
            {
                "output_guardrail": "output_guardrail",
                "retrieve": "retrieve",
                "check_relevance": "check_relevance"
            }
        )
        
        workflow.add_edge("retrieve", "rerank")
        workflow.add_edge("rerank", "check_relevance")
        
        workflow.add_conditional_edges(
            "check_relevance",
            self._route_after_relevance,
            {
                "research": "research",
                "rewrite_query": "rewrite_query", # Cache miss
                "fallback_rewrite": "fallback_rewrite",
                "handle_irrelevant": "handle_irrelevant"
            }
        )
        
        workflow.add_conditional_edges(
            "fallback_rewrite",
            self._route_after_fallback,
            {
                "retrieve": "retrieve",
                "research": "research",
                "handle_irrelevant": "handle_irrelevant"
            }
        )
        workflow.add_edge("handle_irrelevant", "output_guardrail")
        workflow.add_edge("research", "verify")
        
        workflow.add_conditional_edges(
            "verify",
            self._decide_after_verification,
            {
                "re_research": "research",
                "end": "output_guardrail"
            }
        )
        
        workflow.add_edge("output_guardrail", END)
        return workflow.compile(checkpointer=checkpointer)

    def _plan_step(self, state: AgentState) -> Dict:
        logger.info("[DEBUG] Entered _plan_step")
        import time
        start_time = time.time()
        attached_ids = [a["id"] for a in state.get("attachments", [])]
        
        decision = self.planner.plan(
            question=state["question"],
            chat_history=state.get("chat_history", ""),
            attached_document_ids=attached_ids
        )
        
        return {
            "planner_decision": decision.model_dump(),
            "retrieval_attempts": 0,
            "revision_count": 0,
            "retrieval_trace": {
                "raw_query": state["question"],
                "latencies": {"plan": time.time() - start_time}
            }
        }

    def _route_after_plan(self, state: AgentState) -> str:
        decision = state.get("planner_decision", {})
        if not decision.get("needs_retrieval", True):
            logger.info("[DEBUG] Routing to chat_responder")
            return "chat_responder"
            
        logger.info("[DEBUG] Needs retrieval -> Routing to rewrite_query.")
        return "rewrite_query"

    def _route_after_rewrite(self, state: AgentState) -> str:
        if state.get("rewrite_failed", False):
            logger.info("[DEBUG] Rewrite failed and needs chat history -> returning graceful failure via output_guardrail.")
            return "output_guardrail"
        return "check_cache"

    def _check_cache_step(self, state: AgentState) -> Dict:
        import time
        import asyncio
        start_time = time.time()
        logger.info("[DEBUG] Entered _check_cache_step")
        tenant_id = state.get("tenant_id", "default_tenant")
        thread_id = state.get("thread_id", "default_thread")
        query_to_check = state.get("current_query", state["question"])
        
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        exact_answer = loop.run_until_complete(exact_cache_manager.check_cache(query_to_check, tenant_id, thread_id))
        if exact_answer:
            logger.info("[DEBUG] Exact Cache Hit in Workflow.")
            return {"draft_answer": exact_answer}
            
        # Get version to pass to synchronous semantic_cache
        version = loop.run_until_complete(exact_cache_manager.get_tenant_version(tenant_id))
        # semantic_cache is synchronous
        semantic_answer = semantic_cache_manager.check_cache(query_to_check, tenant_id, thread_id, version)
        if semantic_answer:
            logger.info("[DEBUG] Semantic Cache Hit in Workflow.")
            return {"draft_answer": semantic_answer}
            
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["check_cache"] = time.time() - start_time
        return {"retrieval_trace": trace}

    def _route_after_cache(self, state: AgentState) -> str:
        if state.get("draft_answer"):
            return "output_guardrail"
            
        # TODO: Document cache routing intentionally disabled pending future implementation.
        # cached_docs = state.get("cached_documents")
        # if cached_docs:
        #     logger.info("[DEBUG] Cached docs found. Routing to check_relevance.")
        #     return "check_relevance"
            
        logger.info("[DEBUG] No cache. Routing to retrieve.")
        return "retrieve"

    def _chat_responder_step(self, state: AgentState) -> Dict:
        logger.info("[DEBUG] Entered _chat_responder_step")
        prompt = f"""
        Answer the user's question directly based on the conversational history.
        You do not need external documents for this.
        
        Chat History:
        {state.get("chat_history", "")}
        
        User Question: {state["question"]}
        """
        response = self.chat_model.invoke(prompt)
        return {"draft_answer": response.content}

    def _rewrite_query_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info("[DEBUG] Entered _rewrite_query_step")
        decision = state.get("planner_decision", {})
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        
        if not decision.get("needs_query_expansion", True) and not decision.get("needs_chat_history", False):
            trace["standalone_query"] = state["question"]
            trace["retrieval_queries"] = [state["question"]]
            trace["latencies"]["rewrite_query"] = time.time() - start_time
            return {
                "current_query": state["question"],
                "retrieval_queries": [state["question"]],
                "retrieval_trace": trace
            }
            
        new_query_data = self.rewriter.rewrite(
            original_question=state["question"],
            chat_history=state.get("chat_history", ""),
            needs_chat_history=decision.get("needs_chat_history", False)
        )
        
        trace["standalone_query"] = new_query_data["standalone_query"]
        trace["retrieval_queries"] = new_query_data["retrieval_queries"]
        trace["latencies"]["rewrite_query"] = time.time() - start_time
        
        result_state = {
            "current_query": new_query_data["standalone_query"],
            "retrieval_queries": new_query_data["retrieval_queries"],
            "retrieval_trace": trace
        }
        
        if new_query_data.get("rewrite_failed", False):
            result_state["rewrite_failed"] = True
            result_state["draft_answer"] = "I couldn't resolve your follow-up question. Please mention the topic again."
            
        return result_state

    def _retrieve_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info(f"[DEBUG] Entered _retrieve_step")
        queries = state.get("retrieval_queries", [state.get("current_query", state["question"])])
        retriever = state["retriever"]
        
        # Inject document IDs to search from planner
        decision = state.get("planner_decision", {})
        docs_to_search = decision.get("document_ids_to_search", [])
        if hasattr(retriever, 'document_ids'):
            retriever.document_ids = docs_to_search
            
        all_documents = []
        seen_ids = set()
        
        trace = state.get("retrieval_trace", {})
        
        for q in queries:
            logger.info(f"Retrieving for sub-query: {q}")
            documents = retriever.invoke(q)
            
            # Extract trace from retriever if it's our hybrid retriever
            if hasattr(retriever, "last_trace"):
                for k, v in retriever.last_trace.items():
                    if k not in trace: trace[k] = []
                    if isinstance(v, list): trace[k].extend(v)
            
            for doc in documents:
                # Add provenance metadata
                if "retrieved_from_queries" not in doc.metadata:
                    doc.metadata["retrieved_from_queries"] = []
                if q not in doc.metadata["retrieved_from_queries"]:
                    doc.metadata["retrieved_from_queries"].append(q)
                
                doc_id = doc.metadata.get("id", doc.page_content[:50])
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    all_documents.append(doc)
                    
        logger.info(f"Retrieved total {len(all_documents)} unique chunks from database.")
        for i, doc in enumerate(all_documents[:3]): # Log top 3 for debugging
            logger.info(f"  [Chunk {i+1}] Source: {doc.metadata.get('source', 'Unknown')} | Queries: {doc.metadata.get('retrieved_from_queries')} | Text: {doc.page_content[:150]}...")
            
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["retrieve"] = time.time() - start_time
        return {"documents": all_documents, "used_cache": False, "retrieval_trace": trace}

    def _rerank_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info(f"[DEBUG] Entered _rerank_step")
        query = state.get("current_query", state["question"])
        reranked = self.reranker.rerank(query, state["documents"])
        
        logger.info(f"Reranked {len(reranked)} chunks.")
        for i, doc in enumerate(reranked[:3]): # Log top 3 reranked
            rerank_score = doc.metadata.get('rerank_score', doc.metadata.get('vector_score', 0.0))
            logger.info(f"  [LLM Rank {i+1}] Rerank Score: {rerank_score} | Source: {doc.metadata.get('source', 'Unknown')} | Text: {doc.page_content[:150]}...")
            
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["rerank"] = time.time() - start_time
        # Update cache with the new reranked documents
        return {"documents": reranked, "cached_documents": reranked, "retrieval_trace": trace}

    def _check_relevance_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info(f"[DEBUG] Entered _check_relevance_step")
        docs_to_check = state.get("cached_documents") if state.get("used_cache", True) else state["documents"]
        
        result = self.relevance_checker.check(
            query=state.get("current_query", state["question"]), 
            documents=docs_to_check,
            raw_question=state["question"],
            planner_decision=state.get("planner_decision", {})
        )
        
        logger.info(f"Relevance Result: {result.model_dump_json(indent=2)}")
        
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["check_relevance"] = time.time() - start_time
        
        return {
            "relevance_result": result.model_dump(),
            "failure_reason": result.reasoning,
            "documents": docs_to_check, # Lock in the documents used
            "retrieval_trace": trace
        }

    def _route_after_relevance(self, state: AgentState) -> str:
        relevance_result = state.get("relevance_result", {})
        is_sufficient = relevance_result.get("sufficient", False)
        used_cache = state.get("used_cache", False)
        attempts = state.get("retrieval_attempts", 0)
        
        if is_sufficient:
            logger.info("[DEBUG] Relevance is sufficient -> research")
            return "research"
            
        # TODO: Document cache routing intentionally disabled pending future implementation.
        # if used_cache:
        #     # Cache miss - try real retrieval
        #     logger.info("[DEBUG] Cache missed (insufficient evidence). Doing fresh retrieval.")
        #     return "rewrite_query"
            
        if attempts < 1:
            logger.info("[DEBUG] Insufficient evidence, but we haven't tried fallback rewrite yet -> fallback_rewrite")
            return "fallback_rewrite"
            
        planner = state.get("planner_decision", {})
        query_type = planner.get("query_type", "single_entity")
        complex_query = query_type in ["comparison", "sequence", "multi_hop", "follow_up"]
        
        if complex_query and "entity_coverage" in relevance_result:
            if any(score > 0.5 for score in relevance_result["entity_coverage"].values()):
                logger.info("[DEBUG] Out of attempts, but complex query has decent entity coverage. Routing to research.")
                return "research"
                
        logger.info("[DEBUG] No match or out of attempts -> handle_irrelevant")
        return "handle_irrelevant"

    def _fallback_rewrite_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info("[DEBUG] Entered _fallback_rewrite_step")
        original_query = state.get("current_query", state["question"])
        old_queries = state.get("retrieval_queries", [])
        
        new_query_data = self.rewriter.rewrite(
            original_question=original_query, 
            chat_history=state.get("chat_history", ""),
            failure_reason=state.get("failure_reason", "Insufficient context")
        )
        
        new_queries = new_query_data["retrieval_queries"]
        fallback_identical = sorted(new_queries) == sorted(old_queries)
        if fallback_identical:
            logger.info("[DEBUG] Fallback generated identical queries. Short-circuiting redundant retrieval.")

        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["fallback_rewrite"] = time.time() - start_time

        return {
            "current_query": new_query_data["standalone_query"],
            "retrieval_queries": new_queries,
            "retrieval_attempts": state.get("retrieval_attempts", 0) + 1,
            "fallback_identical": fallback_identical,
            "retrieval_trace": trace
        }

    def _route_after_fallback(self, state: AgentState) -> str:
        if state.get("fallback_identical"):
            docs = state.get("documents", [])
            has_docs = len(docs) > 0
            
            planner = state.get("planner_decision", {})
            query_type = planner.get("query_type", "single_entity")
            complex_query = query_type in ["comparison", "sequence", "multi_hop", "follow_up"]
            
            relevance_result = state.get("relevance_result", {})
            decent_coverage = False
            if "entity_coverage" in relevance_result:
                decent_coverage = any(score > 0.5 for score in relevance_result["entity_coverage"].values())
            
            if has_docs and decent_coverage and complex_query:
                logger.info("[DEBUG] Identical fallback, but complex query has decent entity coverage. Routing to research.")
                return "research"
            else:
                logger.info("[DEBUG] Identical fallback and insufficient chunks. Routing to handle_irrelevant.")
                return "handle_irrelevant"
                
        return "retrieve"

    def _handle_irrelevant_step(self, state: AgentState) -> Dict:
        logger.info("[DEBUG] Entered _handle_irrelevant")
        msg = AIMessage(content="I couldn't find enough evidence in the uploaded documents to answer this accurately.")
        return {"draft_answer": msg.content, "messages": [msg], "documents": state.get("documents", []), "cached_documents": state.get("cached_documents"), "turn_status": "no_answer"}

    def _research_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info(f"[DEBUG] Entered _research_step")
        # Use the rewritten query so the Generator has full context of what it's answering
        query_to_answer = state.get("current_query", state["question"])
        result = self.researcher.generate(
            question=query_to_answer, 
            documents=state["documents"], 
            feedback=state.get("feedback"),
            chat_history=state.get("chat_history", "")
        )
        
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["research"] = time.time() - start_time
        
        return {"draft_answer": result["draft_answer"], "retrieval_trace": trace}
    
    def _verification_step(self, state: AgentState) -> Dict:
        import time
        start_time = time.time()
        logger.info("[DEBUG] Entered _verification_step")
        result = self.verifier.check(state["draft_answer"], state["documents"])
        
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["verification"] = time.time() - start_time
        
        return {
            "verification_report": result["verification_report"],
            "failure_reason": result.get("failure_reason", "NONE"),
            "feedback": result["verification_report"],
            "revision_count": state.get("revision_count", 0) + 1,
            "retrieval_trace": trace
        }
    
    def _decide_after_verification(self, state: AgentState) -> str:
        report = state.get("verification_report", "")
        reason = state.get("failure_reason", "NONE")
        revisions = state.get("revision_count", 0)
        
        if "Supported: NO" not in report and "Relevant: NO" not in report:
            return "end"
            
        if revisions >= 2:
            return "end"
            
        if reason == "WRONG_REASONING":
            return "re_research"
            
        return "end"

    def _output_guardrail_step(self, state: AgentState) -> Dict:
        import time
        import os
        import json
        start_time = time.time()
        logger.info("[DEBUG] Entered _output_guardrail_step")
        
        report = state.get("verification_report", "")
        reason = state.get("failure_reason", "NONE")
        revisions = state.get("revision_count", 0)
        
        sanitized_answer = state["draft_answer"]
        turn_status = state.get("turn_status", "success")
        documents = state.get("documents", [])
        
        # Handle Verification Failures
        if "Supported: NO" in report or "Relevant: NO" in report:
            if reason in ["MISSING_EVIDENCE", "NO_ANSWER_IN_DOC"]:
                logger.warning(f"[DEBUG] Verification failed due to {reason}. Overriding answer and clearing docs.")
                sanitized_answer = "I couldn't find enough evidence in the uploaded documents to answer this accurately."
                turn_status = "no_answer"
                documents = [] # Clear citations
            elif revisions >= 2:
                logger.warning("[DEBUG] Verification failed 2 times. Prepending warning.")
                sanitized_answer = "I couldn't verify the reasoning internally. Here is my best attempt: " + sanitized_answer
                turn_status = "no_answer"
        
        try:
            from security.guardrails.pii_guardrail import pii_guardrail
            sanitized_answer = pii_guardrail.sanitize(sanitized_answer)
        except Exception as e:
            logger.error(f"Failed to run output guardrail: {e}")
            
        sanitized_answer = strip_reasoning(sanitized_answer)
            
        trace = state.get("retrieval_trace", {})
        if "latencies" not in trace: trace["latencies"] = {}
        trace["latencies"]["output_guardrail"] = time.time() - start_time
        
        # Save retrieval trace
        if settings.ENABLE_RETRIEVAL_TRACE:
            try:
                os.makedirs("logs", exist_ok=True)
                with open("logs/retrieval_traces.jsonl", "a") as f:
                    f.write(json.dumps(trace) + "\n")
            except Exception as e:
                logger.error(f"Failed to save retrieval trace: {e}")

        # Cache saving is deferred to main.py to allow streaming to start instantly

        state_updates = {
            "draft_answer": sanitized_answer, 
            "turn_status": turn_status,
            "documents": documents,
            "retrieval_trace": trace
        }
        if turn_status == "no_answer" and reason in ["MISSING_EVIDENCE", "NO_ANSWER_IN_DOC"]:
             state_updates["cached_documents"] = []
             state_updates["verification_report"] = f"Verification Failed: {reason}"
             
        return state_updates

    def full_pipeline(self, question: str, retriever: object, chat_history: str = "", thread_id: str = "default_thread", tenant_id: str = "default_tenant", attachments: List[dict] = None):
        try:
            logger.info(f"[DEBUG] Starting pipeline on thread_id='{thread_id}'")
            initial_state = {
                "question": question,
                "chat_history": chat_history,
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "attachments": attachments or [],
                "current_query": question,
                "retrieval_queries": [question],
                "draft_answer": "",
                "verification_report": "",
                "failure_reason": "NONE",
                "relevance_result": {},
                "retriever": retriever,
                "revision_count": 0,
                "retrieval_attempts": 0,
                "feedback": "",
                "used_cache": True,
                "fallback_identical": False,
                "turn_status": "success"
            }
            
            final_state = initial_state
            config = {"configurable": {"thread_id": thread_id}}
            for event in self.compiled_workflow.stream(initial_state, config=config):
                for key, value in event.items():
                    final_state.update(value)
                    yield {"node": key, "state": final_state}
                    
            yield {"node": "final", "state": final_state}
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise

async def save_agent_caches(state: dict):
    turn_status = state.get("turn_status", "success")
    sanitized_answer = state.get("draft_answer", "")
    
    if turn_status == "success" and "I couldn't find enough evidence" not in sanitized_answer:
        decision = state.get("planner_decision", {})
        if decision.get("needs_retrieval", True):
            tenant_id = state.get("tenant_id", "default_tenant")
            thread_id = state.get("thread_id", "default_thread")
            standalone_query = state.get("current_query", state.get("question", ""))
            
            try:
                await exact_cache_manager.set_cache(standalone_query, sanitized_answer, tenant_id, thread_id)
                logger.info(f"[CACHE] Exact: Saved | Status: Verified | Reason: PASS")
                
                metadata = {
                    "planner_type": decision.get("query_type", "single_entity")
                }
                
                def sync_save_semantic(ver):
                    semantic_cache_manager.set_cache(standalone_query, sanitized_answer, tenant_id, thread_id, version=ver, metadata=metadata)
                    
                version = await exact_cache_manager.get_tenant_version(tenant_id)
                await asyncio.to_thread(sync_save_semantic, version)
                logger.info(f"[CACHE] Semantic: Saved | Status: Verified | Reason: PASS")
            except Exception as e:
                logger.error(f"[CACHE] Error saving caches: {e}")
    else:
        logger.info(f"[CACHE] Skipped | Reason: Verification failed or Turn Status is {turn_status}")