import os
import re
from typing import List
from db.models import ChatMessage
import logging
from utils.llm_factory import get_llm
from config.settings import settings
from utils.sanitize import strip_reasoning

logger = logging.getLogger(__name__)

# Configurable memory limit via env. Defaults to 4000 tokens.
MAX_MEMORY_TOKENS = int(os.getenv("MAX_MEMORY_TOKENS", "4000"))

class MemoryManager:
    def __init__(self):
        # We use a fast, lightweight model for summarization from Azure
        self.summarizer_llm = get_llm(
            temperature=0,
            agent_name="summarizer"
        )

    def estimate_tokens(self, text: str) -> int:
        # Standard heuristic: 1 token is approx 4 characters of text
        return len(text) // 4

    def _strip_thinking(self, text: str) -> str:
        """Removes <thinking>...</thinking> blocks to prevent context pollution."""
        return strip_reasoning(text)

    def _is_failed_turn(self, msg: ChatMessage) -> bool:
        """Check if the response indicates a failed retrieval or inability to answer based on metadata."""
        if not msg.metadata_json:
            return False
        return msg.metadata_json.get("status") == "no_answer"

    def compress_history(self, messages: List[ChatMessage]) -> str:
        """Dynamically summarizes chat history if the configurable token threshold is exceeded."""
        if not messages:
            return ""
            
        valid_messages = []
        for msg in messages:
            if msg.role == "assistant" and self._is_failed_turn(msg):
                continue # Skip failed turns to prevent context pollution
            valid_messages.append(msg)
            
        if not valid_messages:
            return ""
            
        full_text = "\n".join([f"{msg.role}: {self._strip_thinking(msg.content)}" for msg in valid_messages])
        total_tokens = self.estimate_tokens(full_text)
        
        if total_tokens <= MAX_MEMORY_TOKENS:
            logger.info(f"Memory within limits ({total_tokens}/{MAX_MEMORY_TOKENS} tokens). No compression needed.")
            return full_text
            
        logger.warning(f"Memory threshold exceeded ({total_tokens}/{MAX_MEMORY_TOKENS} tokens). Triggering summarization...")
        
        # Summarize older messages and keep the 3 most recent completely intact to preserve immediate context
        recent_count = 3
        old_messages = valid_messages[:-recent_count]
        recent_messages = valid_messages[-recent_count:]
        
        old_text = "\n".join([f"{msg.role}: {self._strip_thinking(msg.content)}" for msg in old_messages])
        
        # Prompt the LLM to condense the older history
        prompt = f"Summarize the following chat history concisely, preserving all key facts, entities, and context:\n\n{old_text}"
        summary_response = self.summarizer_llm.invoke(prompt)
        summary = summary_response.content
        
        # Reconstruct the optimized history string
        compressed_text = f"--- Previous Conversation Summary ---\n{summary}\n--- Recent Messages ---\n"
        compressed_text += "\n".join([f"{msg.role}: {self._strip_thinking(msg.content)}" for msg in recent_messages])
        
        return compressed_text

memory_manager = MemoryManager()
