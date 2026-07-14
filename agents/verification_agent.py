import json
from typing import Dict, List, Literal
from langchain_core.documents import Document
from utils.llm_factory import get_llm
from config.settings import settings
from pydantic import BaseModel, Field

# Define Verification Schema
class VerificationResult(BaseModel):
    Supported: Literal["YES", "NO"] = Field(description="Is the answer supported by the context?")
    Unsupported_Claims: List[str] = Field(description="List of unsupported claims", alias="Unsupported Claims")
    Contradictions: List[str] = Field(description="List of contradictions")
    Relevant: Literal["YES", "NO"] = Field(description="Is the answer relevant to the question?")
    Additional_Details: str = Field(description="Any additional details or explanations", alias="Additional Details")
    Failure_Reason: Literal["NONE", "MISSING_EVIDENCE", "WRONG_REASONING", "NO_ANSWER_IN_DOC"] = Field(description="The primary reason for failure if Supported is NO", alias="Failure Reason")

class VerificationAgent:
    def __init__(self):
        """
        Initialize the verification agent with Groq.
        """
        print("Initializing VerificationAgent with Groq...")
        
        self.model = get_llm(
            temperature=0.0,
            max_tokens=1500,
            agent_name="verifier"
        ).bind(response_format={"type": "json_object"})
        
        print("Groq model initialized successfully.")

    def sanitize_response(self, response_text: str) -> str:
        return response_text.strip()

    def generate_prompt(self, answer: str, context: str) -> str:
        prompt = f"""
        You are an AI assistant designed to verify the accuracy and relevance of answers based on the provided context.

        **Instructions:**
        - Verify the following answer against the provided context.
        - Respond strictly with a JSON object.
        - Check for:
        1. Direct/indirect factual support (YES/NO)
        2. Unsupported claims (list any if present)
        3. Contradictions (list any if present)
        4. Relevance to the question (YES/NO)
        5. If Supported is NO, identify the failure reason from these options: MISSING_EVIDENCE, WRONG_REASONING, NO_ANSWER_IN_DOC.
        
        **JSON Format Expected:**
        {{
            "Supported": "YES" or "NO",
            "Unsupported Claims": ["item1", "item2"],
            "Contradictions": ["item1", "item2"],
            "Relevant": "YES" or "NO",
            "Additional Details": "Any extra information or explanations",
            "Failure Reason": "NONE" or "MISSING_EVIDENCE" or "WRONG_REASONING" or "NO_ANSWER_IN_DOC"
        }}

        **Answer:** {answer}
        **Context:**
        {context}
        """
        return prompt

    def parse_verification_response(self, response_text: str) -> Dict:
        try:
            verification = json.loads(response_text)
            for key in ["Supported", "Unsupported Claims", "Contradictions", "Relevant", "Additional Details", "Failure Reason"]:
                if key not in verification:
                    if key in {"Unsupported Claims", "Contradictions"}:
                        verification[key] = []
                    elif key in {"Additional Details"}:
                        verification[key] = ""
                    elif key == "Failure Reason":
                        verification[key] = "NONE"
                    else:
                        verification[key] = "NO"
            return verification
        except Exception as e:
            print(f"Error parsing verification response: {e}")
            return None

    def format_verification_report(self, verification: Dict) -> str:
        supported = verification.get("Supported", "NO")
        unsupported_claims = verification.get("Unsupported Claims", [])
        contradictions = verification.get("Contradictions", [])
        relevant = verification.get("Relevant", "NO")
        additional_details = verification.get("Additional Details", "")
        failure_reason = verification.get("Failure Reason", "NONE")

        report = f"**Supported:** {supported}\n"
        if unsupported_claims:
            report += f"**Unsupported Claims:** {', '.join(unsupported_claims)}\n"
        else:
            report += f"**Unsupported Claims:** None\n"

        if contradictions:
            report += f"**Contradictions:** {', '.join(contradictions)}\n"
        else:
            report += f"**Contradictions:** None\n"

        report += f"**Relevant:** {relevant}\n"
        if additional_details:
            report += f"**Additional Details:** {additional_details}\n"
        else:
            report += f"**Additional Details:** None\n"
            
        report += f"**Failure Reason:** {failure_reason}\n"
        return report

    def check(self, answer: str, documents: List[Document]) -> Dict:
        print(f"VerificationAgent.check called with answer='{answer}' and {len(documents)} documents.")
        context = "\n\n".join([doc.page_content for doc in documents])
        prompt = self.generate_prompt(answer, context)

        try:
            print("Sending prompt to the model...")
            response = self.model.invoke(prompt)
            llm_response = response.content
            if not llm_response:
                print("Groq returned no text content.")
            print("LLM response received.")
        except Exception as e:
            print(f"Error during model inference: {e}")
            raise RuntimeError("Failed to verify answer due to a model error.") from e

        sanitized_response = self.sanitize_response(llm_response) if llm_response else ""
        if not sanitized_response:
            print("LLM returned an empty response.")
            verification_report = {
                "Supported": "NO",
                "Unsupported Claims": [],
                "Contradictions": [],
                "Relevant": "NO",
                "Additional Details": "Empty response from the model.",
                "Failure Reason": "NONE"
            }
        else:
            verification_report = self.parse_verification_response(sanitized_response)
            if verification_report is None:
                verification_report = {
                    "Supported": "NO",
                    "Unsupported Claims": [],
                    "Contradictions": [],
                    "Relevant": "NO",
                    "Additional Details": "Failed to parse the model's response.",
                    "Failure Reason": "NONE"
                }

        verification_report_formatted = self.format_verification_report(verification_report)
        print(f"Verification report:\n{verification_report_formatted}")

        return {
            "verification_report": verification_report_formatted,
            "failure_reason": verification_report.get("Failure Reason", "NONE"),
            "context_used": context
        }
