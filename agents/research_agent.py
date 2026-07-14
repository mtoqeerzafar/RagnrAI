from typing import Dict, List
from langchain_core.documents import Document
from utils.llm_factory import get_llm
from config.settings import settings
import json

class ResearchAgent:
    def __init__(self):
        """
        Initialize the research agent with Groq.
        """
        print("Initializing ResearchAgent with Groq...")
        
        self.model = get_llm(
            temperature=0.3,
            max_tokens=2048,
            agent_name="researcher"
        )
        
        print("Groq model initialized successfully.")

    def sanitize_response(self, response_text: str) -> str:
        """
        Sanitize the LLM's response by stripping unnecessary whitespace.
        """
        return response_text.strip()

    def generate_prompt(self, question: str, context: str, feedback: str = None, chat_history: str = "") -> str:
        """
        Generate a structured prompt for the LLM to generate a precise and factual answer.
        """
        prompt = f"""
        You are an AI assistant designed to provide precise and factual answers based on the given context.

        **Instructions:**
        1. Read the provided context carefully.
        2. Before writing the final answer, write out your reasoning steps inside `<thinking>` and `</thinking>` tags.
        3. After the `</thinking>` block, provide the final factual answer.
        4. Answer the following question using only the provided context.
        5. Be clear, concise, and factual.
        6. When extracting details from a specific section, extract **every single instance** where the target keyword appears within that section's boundary. Do not skip or filter out steps based on localized phrasing.

        ### CRITICAL BOUNDARY ENFORCEMENT:
        1. You are a literal extraction engine. You are FORBIDDEN from using logic, reasoning, or analogy to decide if two different workflows are "similar" or "applicable."
        2. If a query asks about a specific named procedure (e.g., "Resignation"), your search space is strictly isolated to that specific text block or table.
        3. If a step appears under a different procedure heading (such as "Termination of Service" or "Retirement"), you must completely ignore it, even if it contains identical keywords or performs a similar administrative function.
        4. Do not rationalize or infer cross-procedure workflows. However, if the user asks about the sequence of events (e.g., "What happens before X?"), you are permitted and encouraged to logically connect the sequential steps that are clearly outlined in the context.
        """
        if chat_history:
            prompt += f"""
        **Previous Conversation History:**
        {chat_history}
        """

        if feedback:
            prompt += f"""
        - PREVIOUS ATTEMPT FEEDBACK: The following feedback was provided on a previous draft. Please address these issues in your reasoning and answer:
        {feedback}
        """

        prompt += f"""
        **Question:** {question}
        **Context:**
        {context}

        **Provide your answer below:**
        """
        return prompt

    def generate(self, question: str, documents: List[Document], feedback: str = None, chat_history: str = "") -> Dict:
        """
        Generate an initial answer using the provided documents.
        """
        print(f"ResearchAgent.generate called with question='{question}' and {len(documents)} documents.")

        # Combine the top document contents into one string
        context = "\n\n".join([doc.page_content for doc in documents])
        print(f"Combined context length: {len(context)} characters.")

        # Create a prompt for the LLM
        prompt = self.generate_prompt(question, context, feedback, chat_history)
        print("Prompt created for the LLM.")

        # Call the Groq model to generate the answer
        try:
            print("Sending prompt to the model...")
            response = self.model.invoke(prompt)
            llm_response = response.content
            if not llm_response:
                print("Groq returned no text content.")
            print("LLM response received.")
            print(f"Raw LLM response:\n{llm_response}")
        except Exception as e:
            print(f"Error during model inference: {e}")
            raise RuntimeError(f"Research agent model inference failed: {e}") from e

        # Sanitize the response
        draft_answer = self.sanitize_response(llm_response) if llm_response else "I cannot answer this question based on the provided documents."

        print(f"Generated answer: {draft_answer}")

        return {
            "draft_answer": draft_answer,
            "context_used": context
        }
