import os
import logging

logger = logging.getLogger(__name__)

def setup_observability():
    """
    Initializes LangSmith tracing across the entire LangGraph workflow.
    This provides fine-grained visibility into agent routing, LLM calls, and retries.
    """
    if os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGCHAIN_PROJECT", "ragnrai-production")
        logger.info("LangSmith observability initialized successfully.")
    else:
        logger.warning("LANGCHAIN_API_KEY not found. LangSmith tracing is disabled.")
