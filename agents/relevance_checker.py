import logging
import json
from typing import List, Literal, Dict
from pydantic import BaseModel, Field
from utils.llm_factory import get_llm
from langchain_core.documents import Document
from config.settings import settings

logger = logging.getLogger(__name__)

class RelevanceResult(BaseModel):
    sufficient: bool = Field(description="True if there is sufficient evidence in the provided documents to answer the question or synthesize a response.")
    reasoning: str = Field(description="A detailed, actionable explanation of why the evidence was deemed sufficient or insufficient (e.g., 'Entity B is missing sufficient descriptive context for comparison').")
    evidence_type: Literal["complete", "partial", "missing_entity", "missing_step", "missing_relation"] = Field(description="Categorization of the evidence completeness.")
    entity_coverage: Dict[str, float] = Field(description="Dictionary mapping each distinct entity/concept in the query to a coverage score (0.0 to 1.0) indicating how well it is represented in the chunks.", default_factory=dict)
    missing_entities: List[str] = Field(description="List of entities explicitly missing from the documents.", default_factory=list)
    missing_relations: List[str] = Field(description="List of relationships or comparisons explicitly missing from the documents.", default_factory=list)

class RelevanceChecker: 
    def __init__(self):
        self.model = get_llm(
            temperature=0,
            max_tokens=400
        ).with_structured_output(RelevanceResult, method="function_calling")

    def check(self, query: str, documents: List[Document], raw_question: str = None, planner_decision: dict = None) -> RelevanceResult:
        """Evaluate relevance of documents to the question."""
        logger.debug(f"RelevanceChecker.check called with query='{query}' and {len(documents)} documents")

        if not documents:
            return RelevanceResult(
                sufficient=False, 
                reasoning="No documents provided.",
                evidence_type="missing_entity",
                entity_coverage={},
                missing_entities=["all"],
                missing_relations=[]
            )

        planner_decision = planner_decision or {}
        query_type = planner_decision.get("query_type", "single_entity")

        context_text = "\n\n".join(doc.page_content for doc in documents)

        prompt = f"""
        You are an AI relevance checker between a user's question and provided document content.

        **Instructions:**
        1. Evaluate if the passages provide enough foundational context, facts, or grounding to answer the question or perform the requested reasoning.
        2. Consider the query type: `{query_type}`.
           - If `comparison`: Evaluate each entity independently. Populate `entity_coverage` with a score for EACH distinct entity in the question (e.g. {{"TCP": 0.9, "UDP": 0.2}}). PASS (`sufficient=true`) only if both entities have sufficient descriptive evidence AND together the retrieved evidence is enough for the generator to compare them. The documents DO NOT need to explicitly compare them; the generator will do that.
           - If `sequence`: PASS (`sufficient=true`) only if the specific steps or process flow are sufficiently detailed.
           - If `multi_hop`: PASS (`sufficient=true`) if sufficient evidence for the various reasoning hops is present.
           - If `single_entity`: PASS (`sufficient=true`) if the specific entity is covered with enough detail to answer the question.
        3. Provide detailed `reasoning` and categorize the `evidence_type`.
        4. Extract missing elements into `missing_entities` and `missing_relations`.
        
        **CRITICAL RULE — SYNTHESIS & DERIVATION TASKS:**
        When the user asks the system to CREATE, WRITE, DERIVE, FORMULATE, or SUMMARIZE something (e.g., "write the equation", "create a table", "summarize the steps", "derive the formula"), you must evaluate whether the documents contain enough **foundational information** (descriptions of processes, steps, relationships, concepts) for the generator to synthesize the requested output.
        Do NOT require the exact final output (equation, table, formula, summary) to already exist verbatim in the documents. The generator's job is to synthesize it from the provided context.
        Example: If the user asks "write the equation for Process X" and the documents describe Process X's steps and relationships in detail, that IS sufficient — mark `sufficient=true`.

        **CRITICAL JSON INSTRUCTIONS:**
        - You MUST output valid JSON.
        - Booleans MUST be lowercase `true` or `false`. Do NOT use Python's `True` or `False`.

        **Query (Rewritten/Standalone):** {query}
        **Original Raw Question (for context):** {raw_question or "N/A"}
        **Query Type:** {query_type}
        
        **Documents:**
        {context_text}
        """

        try:
            result = self.model.invoke(prompt)
            return result
        except Exception as e:
            logger.error(f"Error during model inference: {e}")
            raise e
