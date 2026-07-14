import logging
import torch
from transformers import pipeline
from typing import Dict

logger = logging.getLogger(__name__)

class PromptInjectionGuardrail:
    """
    Detects prompt injection and jailbreak attempts using a lightweight,
    locally running DeBERTa model fine-tuned for prompt injection detection.
    This ensures sub-100ms latency without relying on external APIs.
    """
    def __init__(self):
        self.model_name = "protectai/deberta-v3-base-prompt-injection-v2"
        logger.info(f"Loading Prompt Injection model: {self.model_name}...")
        try:
            # Load the classifier
            # device=0 uses GPU if available, else -1 for CPU
            device = 0 if torch.cuda.is_available() else -1
            self.classifier = pipeline(
                "text-classification",
                model=self.model_name,
                device=device
            )
            logger.info("Prompt Injection model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Prompt Injection model: {e}")
            # If the model fails to load, we don't want to crash the whole app,
            # but we must fail open or closed depending on risk appetite.
            self.classifier = None

        # Heuristic blacklist as a fallback/fast-path
        self.blacklist_phrases = [
            "ignore all previous instructions",
            "ignore previous instructions",
            "system prompt",
            "you are now a",
            "forget everything",
            "disregard all",
            "output your instructions",
            "print your prompt"
        ]

    def _check_heuristics(self, text: str) -> bool:
        """Fast regex/keyword matching for obvious injections."""
        text_lower = text.lower()
        for phrase in self.blacklist_phrases:
            if phrase in text_lower:
                return True
        return False

    def scan(self, prompt: str) -> Dict[str, any]:
        """
        Scans a user prompt for injection attacks.
        Returns a dict: {"is_injection": bool, "confidence": float, "reason": str}
        """
        if not prompt or not prompt.strip():
            return {"is_injection": False, "confidence": 1.0, "reason": "Empty prompt"}

        # 1. Fast path: Heuristics
        if self._check_heuristics(prompt):
            logger.warning(f"Heuristic injection detected in prompt: {prompt}")
            return {"is_injection": True, "confidence": 1.0, "reason": "Matched blacklist phrase"}

        # 2. Deep path: ML Model
        if self.classifier:
            try:
                # The protectai model usually outputs 'INJECTION' or 'SAFE'
                result = self.classifier(prompt, truncation=True, max_length=512)[0]
                label = result["label"]
                score = result["score"]
                
                # Depending on the exact model version, labels might be 'INJECTION' or '1'
                if label == "INJECTION" or label == "LABEL_1" or label == 1:
                    is_injection = True
                else:
                    is_injection = False

                if is_injection and score > 0.6:  # Threshold
                    logger.warning(f"ML injection detected (score={score:.2f})")
                    return {"is_injection": True, "confidence": score, "reason": "Model classification"}
                else:
                    return {"is_injection": False, "confidence": score, "reason": "Safe"}
            except Exception as e:
                logger.error(f"Error running ML prompt injection scan: {e}")
                # Fallback to safe if model errors out during inference
                return {"is_injection": False, "confidence": 0.0, "reason": f"Model error: {str(e)}"}
        
        # If no model is loaded and heuristics passed, assume safe
        return {"is_injection": False, "confidence": 0.0, "reason": "No model loaded, heuristics passed"}

# Singleton instance
prompt_guardrail = PromptInjectionGuardrail()
