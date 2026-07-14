import json
import logging
from utils.llm_factory import get_llm
from config.settings import settings

logger = logging.getLogger(__name__)

class QueryRewriter:
    def __init__(self):
        """Initialize the Query Rewriter Agent."""
        self.model = get_llm(
            temperature=0.1,
            max_tokens=500,
            agent_name="query_rewriter"
        ).bind(response_format={"type": "json_object"})

    def _semantic_judge(self, original_question: str, rewritten_query: str, chat_history: str, resolved_entities: list = None) -> dict:
        entities_str = json.dumps(resolved_entities) if resolved_entities else "[]"
        prompt = f"""
        You are an expert Semantic Judge evaluating a rewritten search query in a conversational RAG system.
        
        **Original Question:** {original_question}
        **Rewritten Query:** {rewritten_query}
        **Resolved Entities Claimed:** {entities_str}
        **Conversation History:** 
        {chat_history}
        
        **Your Task:**
        Determine if the Rewritten Query faithfully preserves the user's FULL intent from the Original Question while resolving ambiguous references.
        Verify that EVERY entity in `Resolved Entities Claimed` exactly exists in the Conversation History.
        
        **CRITICAL RULES:**
        1. PRONOUN & REFERENCE RESOLUTION: The primary goal of the Rewritten Query is to replace ambiguous words (like "it", "this", "the process", "these") with the specific explicit entities they refer to from the Conversation History.
        2. ACCEPTING RESOLVED ENTITIES: If the Rewritten Query contains specific terms or entities that were NOT in the Original Question, you MUST check if those terms exist in the Conversation History. If they DO exist in the Conversation History and correctly resolve an ambiguous reference, this is a PERFECT rewrite and MUST be accepted. Do NOT label this as "hallucination" or "introducing new entities".
        3. TRUE HALLUCINATIONS: You must ONLY reject the rewrite for "hallucinated entities" if the newly introduced entities exist NOWHERE in the Original Question AND NOWHERE in the Conversation History. 
        4. INTENT PRESERVATION: Aside from replacing ambiguous references with explicit history entities, the Rewritten Query must ask the exact same core question. If it adds new sub-questions, adds new constraints not implied by the context, or generalizes the phrasing (e.g. changing "account opening" to "account type"), you must reject it.
        5. ENTITY VERIFICATION: If `Resolved Entities Claimed` is not empty, you MUST verify that `resolved_entities` is a strict subset of entities found in the chat history. If an entity is claimed but wasn't in the history, reject it immediately.
        6. When reporting `resolved_references`, ensure the `resolved_to` text EXACTLY matches what was swapped into the Rewritten Query.

        **Output Schema:**
        Must be a JSON object exactly matching this structure:
        {{
            "preserves_intent": true/false,
            "resolved_references": {{
                "<ambiguous word like 'it'>": {{
                    "resolved_to": "<the exact explicit entity from the conversation history that replaces the ambiguous pronoun/word>",
                    "source": "conversation_history"
                }}
            }},
            "issues": [
                {{
                    "type": "<A short uppercase string describing the error type (e.g., ENTITY_DROPPED, HALLUCINATION, REFERENCE_UNRESOLVED, or any other appropriate category)>",
                    "severity": "warning|error",
                    "confidence": <float 0.0-1.0>,
                    "message": "<description of issue>"
                }}
            ],
            "decision": "accept|reject"
        }}
        """
        try:
            response = self.model.invoke(prompt)
            result = json.loads(response.content)
            return result
        except Exception as e:
            logger.error(f"Semantic Judge failed: {e}")
            return {"decision": "reject", "issues": [{"type": "JUDGE_ERROR", "severity": "error", "confidence": 1.0, "message": str(e)}]} # Fail closed

    def _generate_rewrite(self, original_question: str, chat_history: str, issues: list = None, needs_chat_history: bool = False) -> str:
        issue_text = ""
        if issues:
            issues_str = json.dumps(issues, indent=2)
            issue_text = f"\n**Your previous attempt failed with these issues:**\n{issues_str}\nPlease fix these issues and try again."

        expected_json = """{
            "standalone_query": "<the_final_standalone_query>",
            "retrieval_queries": ["<search_query_1>", "<search_query_2>"],
            "resolved_entities": ["<explicit_entity_from_history_1>", "<explicit_entity_from_history_2>"]
        }"""

        prompt = f"""
        You are an AI reference resolver for conversational search.
        {issue_text}
        
        **Core Invariants:**
        1. Preserve user intent completely.
        2. Resolve references ONLY from the exact entities in the chat history. NEVER invent a new category, generalize an entity (e.g., turning "account opening" into "account types"), or introduce an external term.
        3. Resolve references ONLY when the referent is strongly supported by the conversation history. Use concise, specific entity names (e.g., "Answer Generation") rather than copying entire descriptive sentences.
        4. YOU MUST RESOLVE ALL AMBIGUOUS REFERENCES. If the query has multiple pronouns or ambiguous terms (e.g., "Why is this necessary? Couldn't we skip it?"), resolve EVERY SINGLE ONE of them. Do not leave any "it", "this", or "that" unresolved if the history provides the answer.
        5. Never delete, rename, paraphrase, merge, or replace an entity explicitly mentioned in the latest user question. Only resolve unresolved references.
        6. Produce exactly ONE `standalone_query` representing the latest question.
        7. Do not answer the question itself.
        8. If the question asks to compare or discuss multiple distinct entities (e.g. A vs B) or covers multiple topics, decompose them into separate `retrieval_queries`.

        **Examples of correct rewriting behavior:**

        [Example 1: Pronoun Resolution]
        History: 
        User: The Eiffel Tower was completed in 1889.
        Assistant: It is located in Paris.
        User: Why is it important?
        Output: {{"standalone_query": "Why is the Eiffel Tower important?", "retrieval_queries": ["Why is the Eiffel Tower important?"], "resolved_entities": ["Eiffel Tower"]}}

        [Example 2: Implicit Reference]
        History: 
        User: Gradient Descent is an optimization algorithm.
        Assistant: It minimizes the loss function.
        User: Show the equation for the algorithm.
        Output: {{"standalone_query": "Show the equation for Gradient Descent.", "retrieval_queries": ["Show the equation for Gradient Descent."], "resolved_entities": ["Gradient Descent"]}}

        [Example 3: Comparison]
        History: 
        User: TCP establishes reliable connections.
        Assistant: Yes, it ensures packet delivery.
        User: How is this different from UDP?
        Output: {{"standalone_query": "How is TCP different from UDP?", "retrieval_queries": ["TCP establishes reliable connections", "UDP"], "resolved_entities": ["TCP", "UDP"]}}

        [Example 4: Sequential Logic]
        History: 
        User: What is Model Evaluation?
        Assistant: The final stage is Model Evaluation.
        User: What happens before that step?
        Output: {{"standalone_query": "What happens immediately before Model Evaluation?", "retrieval_queries": ["What happens immediately before Model Evaluation?"], "resolved_entities": ["Model Evaluation"]}}

        [Example 5: Multi-Topic Focus (Realistic Chat)]
        History: 
        User: Explain Photosynthesis.
        Assistant: [Explanation...]
        User: Explain Cellular Respiration.
        Assistant: [Explanation...]
        User: Go back to the first one.
        Output: {{"standalone_query": "Tell me more about Photosynthesis.", "retrieval_queries": ["Photosynthesis"], "resolved_entities": ["Photosynthesis"]}}

        [Example 6: Explicit Entity Preservation (Don't Rewrite)]
        History: 
        User: Python is dynamically typed.
        Assistant: Yes, types are checked at runtime.
        User: Compare Python with Java.
        Output: {{"standalone_query": "Compare Python with Java.", "retrieval_queries": ["Python", "Java"], "resolved_entities": []}}

        [Example 7: New Topic (Ignore History)]
        History: 
        User: Explain PostgreSQL.
        Assistant: It is a relational database.
        User: What is Kubernetes?
        Output: {{"standalone_query": "What is Kubernetes?", "retrieval_queries": ["Kubernetes"], "resolved_entities": []}}

        [Example 8: Don't Invent Semantics]
        History: 
        User: The document discusses PostgreSQL.
        Assistant: It is a relational database.
        User: How does Redis improve this?
        Output: {{"standalone_query": "How does Redis improve PostgreSQL?", "retrieval_queries": ["Redis", "PostgreSQL"], "resolved_entities": ["PostgreSQL"]}}

        [Example 9: Document QA Context (Domain Specific)]
        History: 
        User: What is Hybrid Search?
        Assistant: The document describes Hybrid Search.
        User: How is this different from BM25?
        Output: {{"standalone_query": "How is Hybrid Search different from BM25?", "retrieval_queries": ["Hybrid Search", "BM25"], "resolved_entities": ["Hybrid Search"]}}

        [Example 10: Strict Entity Resolution without Generalization]
        History: 
        User: What are the rules for account opening?
        Assistant: [Rules...]
        User: What about dormant accounts?
        Assistant: [Rules...]
        User: Which one has more customer responsibilities?
        Output: {{"standalone_query": "Between account opening and dormant accounts, which involves more customer responsibilities?", "retrieval_queries": ["account opening", "dormant accounts"], "resolved_entities": ["account opening", "dormant accounts"]}}

        [Example 11: Resolving Multiple References with Multiple Entities in History]
        History: 
        User: Tell me about Solar Panels and Wind Turbines.
        Assistant: Solar Panels capture sunlight. Wind Turbines harness wind energy.
        User: Why are these necessary? Couldn't we skip them?
        Output: {{"standalone_query": "Why are Solar Panels and Wind Turbines necessary? Couldn't we skip Solar Panels and Wind Turbines?", "retrieval_queries": ["Why are Solar Panels necessary?", "Why are Wind Turbines necessary?"], "resolved_entities": ["Solar Panels", "Wind Turbines"]}}
        
        **Current Conversation:**
        {chat_history}

        **Current User Question:** {original_question}

        **Expected JSON Output Schema:**
        {expected_json}
        """
        try:
            response = self.model.invoke(prompt)
            logger.info(f"[_generate_rewrite] Raw LLM Response: {response.content}")
            result = json.loads(response.content)
            
            # Normalize to ensure schema compliance
            if "standalone_query" not in result:
                result["standalone_query"] = result.get("rewritten_query", original_question)
            if "retrieval_queries" not in result:
                result["retrieval_queries"] = [result["standalone_query"]]
                
            # Deduplicate and cap at 3
            seen = set()
            deduped = []
            for q in result["retrieval_queries"]:
                if q not in seen:
                    seen.add(q)
                    deduped.append(q)
            result["retrieval_queries"] = deduped[:3]
                
            logger.info(f"[_generate_rewrite] Extracted Standalone: {result['standalone_query']}")
            return result
        except Exception as e:
            logger.error(f"Failed to generate rewrite: {e}")
            return {
                "standalone_query": original_question,
                "retrieval_queries": [original_question]
            }

    def rewrite(self, original_question: str, chat_history: str = "", failure_reason: str = None, debug: bool = False, needs_chat_history: bool = False) -> dict:
        logger.info(f"QueryRewriter invoked for question: '{original_question}' | History Length: {len(chat_history)} chars")

        fallback_result = {
            "standalone_query": original_question,
            "retrieval_queries": [original_question]
        }

        if not chat_history or len(chat_history.strip()) == 0:
            return fallback_result

        # Attempt 1
        initial_issues = None
        if failure_reason:
            initial_issues = [{"type": "PREVIOUS_SEARCH_FAILED", "message": f"Previous search failed because: {failure_reason}. Rewrite the queries to target the missing entities or relationships."}]
            logger.info(f"Applying failure feedback to rewrite: {failure_reason}")
            
        result = self._generate_rewrite(original_question, chat_history, issues=initial_issues, needs_chat_history=needs_chat_history)
        if "resolved_entities" not in result:
            result["resolved_entities"] = []
        rewritten = result["standalone_query"]
        
        if rewritten == original_question and not needs_chat_history:
            return result

        judge_result = self._semantic_judge(original_question, rewritten, chat_history, result.get("resolved_entities", []))
        logger.info(f"Judge Result (Attempt 1): {json.dumps(judge_result)}")

        if judge_result.get("decision") == "accept":
            logger.info(f"Query rewritten to: '{rewritten}'")
            return result
            
        # Attempt 2 (Retry)
        logger.warning(f"Judge rejected rewrite. Retrying... Issues: {json.dumps(judge_result.get('issues', []))}")
        result_v2 = self._generate_rewrite(original_question, chat_history, issues=judge_result.get("issues"), needs_chat_history=needs_chat_history)
        rewritten_v2 = result_v2["standalone_query"]
        
        judge_result_v2 = self._semantic_judge(original_question, rewritten_v2, chat_history, result_v2.get("resolved_entities", []))
        logger.info(f"Judge Result (Attempt 2): {json.dumps(judge_result_v2)}")

        if judge_result_v2.get("decision") == "accept":
            logger.info(f"Query rewritten (v2) to: '{rewritten_v2}'")
            return result_v2

        # Fallback
        logger.warning("Falling back to original query after 2 failed attempts.")
        if needs_chat_history:
            fallback_result["rewrite_failed"] = True
        return fallback_result
