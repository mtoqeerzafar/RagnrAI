import logging
from typing import List
from pydantic import BaseModel, Field, model_validator
from utils.llm_factory import get_llm
from config.settings import settings
from enum import Enum
import json

logger = logging.getLogger(__name__)

class QueryType(str, Enum):
    SINGLE_ENTITY = "single_entity"
    COMPARISON = "comparison"
    MULTI_HOP = "multi_hop"
    FOLLOW_UP = "follow_up"
    REFERENCE_QUERY = "reference_query"

class PlannerDecision(BaseModel):
    query_type: QueryType = Field(description="Classification of the query type.")
    needs_chat_history: bool = Field(description="True if the question refers to previous conversational context or asks about chat history.")
    needs_retrieval: bool = Field(description="True if the question asks for factual information, requires document retrieval, or needs external knowledge.")
    needs_query_expansion: bool = Field(description="True if the question needs rewriting, decomposition, or pronoun resolution.")
    document_ids_to_search: List[str] = Field(description="List of document IDs (UUIDs) to search. Leave empty to search all thread documents if no specific document is implied.")

    @model_validator(mode="after")
    def enforce_query_rules(self):
        # Enforce expansion for complex/dependent queries
        if self.query_type in {
            QueryType.FOLLOW_UP,
            QueryType.COMPARISON,
            QueryType.MULTI_HOP
        }:
            self.needs_query_expansion = True

        # Enforce history for follow-ups
        if self.query_type == QueryType.FOLLOW_UP:
            self.needs_chat_history = True

        return self

class WorkflowPlanner:
    def __init__(self):
        """Initialize the Workflow Planner Agent."""
        self.model = get_llm(
            temperature=0.1,
            max_tokens=500,
            agent_name="planner"
        ).bind(response_format={"type": "json_object"})

    def plan(self, question: str, chat_history: str, attached_document_ids: List[str]) -> PlannerDecision:
        logger.info(f"WorkflowPlanner analyzing question: '{question}'")
        
        prompt = f"""
        You are the orchestration planner for an advanced RAG AI assistant.
        Analyze the user's question and determine the execution plan and query classification.

        **Instructions:**
        1. Classify the query into one of these `query_type`s:
           - "single_entity": A standalone question about a single topic.
           - "comparison": A question comparing two or more entities or concepts.
           - "multi_hop": A complex question requiring multiple steps of reasoning or retrieving multiple distinct pieces of information.
           - "follow_up": A question that relies on the conversation history (contains pronouns or implicit references).
           - "reference_query": A question asking about a specific numbered clause, point, rule, policy, requirement, article, or section (e.g., "Clause 17", "Section 9").
           
        2. Set `needs_chat_history` based on this semantic rule:
           Set `needs_chat_history = True` ONLY IF the user omits entities OR the meaning depends on previous turns OR pronouns cannot be resolved without history. Do not use hardcoded pronoun lists (e.g. "What is the purpose of this policy?" does NOT refer to history, it refers to the document).
        
        3. `needs_retrieval`: ALWAYS True UNLESS the user is just saying "hello", "thanks", "goodbye", or chatting completely casually without needing factual answers.
        
        4. `needs_query_expansion`: True if the query needs rewriting to resolve pronouns, or decomposition into multiple search queries (comparison/multi_hop).
        
        5. `document_ids_to_search`: If `Attached Document IDs` is NOT empty, output those exact IDs into `document_ids_to_search` to scope the search to just those files. If it IS empty, leave `document_ids_to_search` empty.

        **EXAMPLES OF CORRECT DECISIONS:**

        Example 1 (Follow Up):
        Conversation History:
        User: "What is Prompt Injection and Answer Generation?"
        Current Question: "Why is this stage necessary?"
        Attached Document IDs: []
        Decision:
        {{
            "query_type": "follow_up",
            "needs_query_expansion": true,
            "needs_chat_history": true,
            "needs_retrieval": true,
            "document_ids_to_search": []
        }}

        Example 2 (Comparison):
        Conversation History:
        User: "What is Query Processing?"
        Current Question: "How is this different from Retrieval?"
        Attached Document IDs: []
        Decision:
        {{
            "query_type": "comparison",
            "needs_query_expansion": true,
            "needs_chat_history": true,
            "needs_retrieval": true,
            "document_ids_to_search": []
        }}

        Example 3 (Multi Hop):
        Conversation History: None
        Current Question: "Explain the ingestion pipeline and how embeddings are generated."
        Attached Document IDs: []
        Decision:
        {{
            "query_type": "multi_hop",
            "needs_query_expansion": true,
            "needs_chat_history": false,
            "needs_retrieval": true,
            "document_ids_to_search": []
        }}

        Example 4 (Single Entity - Negative Example for Expansion):
        Conversation History: None
        Current Question: "What is BM25 retrieval?"
        Attached Document IDs: []
        Decision:
        {{
            "query_type": "single_entity",
            "needs_query_expansion": false,
            "needs_chat_history": false,
            "needs_retrieval": true,
            "document_ids_to_search": []
        }}

        Example 5 (Single Entity - Negative Example for Expansion):
        Conversation History: None
        Current Question: "Explain Qdrant architecture."
        Attached Document IDs: ["doc-123"]
        Decision:
        {{
            "query_type": "single_entity",
            "needs_query_expansion": false,
            "needs_chat_history": false,
            "needs_retrieval": true,
            "document_ids_to_search": ["doc-123"]
        }}

        Example 6 (Reference Query):
        Conversation History: None
        Current Question: "What are the rules mentioned in Clause 17?"
        Attached Document IDs: []
        Decision:
        {{
            "query_type": "reference_query",
            "needs_query_expansion": false,
            "needs_chat_history": false,
            "needs_retrieval": true,
            "document_ids_to_search": []
        }}

        **CURRENT INPUT:**

        **User Question:** {question}
        
        **Available Chat History (if any):**
        {chat_history}
        
        **Currently Attached Document IDs:**
        {attached_document_ids}
        
        IMPORTANT: You MUST return ONLY a JSON object matching the examples above exactly.
        """
        
        try:
            response = self.model.invoke(prompt)
            data = json.loads(response.content)
            decision = PlannerDecision(**data)
            logger.info(f"Planner Decision: {decision.model_dump()}")
            return decision
        except Exception as e:
            logger.error(f"Failed to plan workflow: {e}. Falling back to default decision.")
            # Fallback to a safe, general RAG behavior to prevent crashing
            return PlannerDecision(
                query_type=QueryType.SINGLE_ENTITY,
                needs_chat_history=True,
                needs_retrieval=True,
                needs_query_expansion=True,
                document_ids_to_search=attached_document_ids
            )
