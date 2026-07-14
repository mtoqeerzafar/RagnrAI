import pytest
import os
import sys

# Add the project root to the sys path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.planner import WorkflowPlanner, QueryType

def test_planner_greeting():
    planner = WorkflowPlanner()
    decision = planner.plan("Hello", "", [])
    assert decision.needs_retrieval == False

def test_planner_thanks():
    planner = WorkflowPlanner()
    decision = planner.plan("Thank you", "Assistant: Here is the info.", [])
    assert decision.needs_retrieval == False

def test_planner_single_entity():
    planner = WorkflowPlanner()
    decision = planner.plan("What is RAG?", "", [])
    assert decision.query_type == QueryType.SINGLE_ENTITY
    assert decision.needs_retrieval == True
    # LLM might randomly set needs_chat_history or needs_query_expansion, 
    # but based on prompt examples, it shouldn't for single_entity.
    # We mainly test that the type is correct.
    assert decision.needs_query_expansion == False
    assert decision.needs_chat_history == False

def test_planner_followup():
    planner = WorkflowPlanner()
    decision = planner.plan("How does this algorithm work?", "Assistant: We introduced Dense Vectors.", [])
    assert decision.query_type == QueryType.FOLLOW_UP
    assert decision.needs_retrieval == True
    assert decision.needs_query_expansion == True
    assert decision.needs_chat_history == True

def test_planner_comparison():
    planner = WorkflowPlanner()
    decision = planner.plan("Difference between BM25 and Dense Retrieval?", "", [])
    assert decision.query_type == QueryType.COMPARISON
    assert decision.needs_retrieval == True
    assert decision.needs_query_expansion == True

def test_planner_multi_hop():
    planner = WorkflowPlanner()
    decision = planner.plan("Explain ingestion + retrieval + generation flow", "", [])
    assert decision.query_type == QueryType.MULTI_HOP
    assert decision.needs_retrieval == True
    assert decision.needs_query_expansion == True

def test_planner_followup_real_world():
    planner = WorkflowPlanner()
    chat_history = "User: What is Model Evaluation?\nAssistant: The final stage is Model Evaluation."
    decision = planner.plan("Why is this stage necessary?", chat_history, [])
    assert decision.query_type == QueryType.FOLLOW_UP
    assert decision.needs_retrieval == True
    assert decision.needs_query_expansion == True
    assert decision.needs_chat_history == True
