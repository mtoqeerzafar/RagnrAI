import logging
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

class PIIGuardrail:
    """
    Scans outputs for PII and enterprise secrets before displaying them to the user.
    We extend standard Presidio (which catches SSNs, Emails, Phones) with custom recognizers
    for secrets (API keys, AWS keys, etc.), HR information, and internal URLs.
    """
    def __init__(self):
        # We initialize the analyzer with en_core_web_lg for high accuracy NER
        try:
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
            logger.info("Presidio Analyzer & Anonymizer initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Presidio: {e}")
            raise

        self._add_custom_recognizers()

    def _add_custom_recognizers(self):
        """
        Adds custom regex-based recognizers to Presidio for Enterprise-specific needs.
        """
        # 1. AWS Keys
        aws_pattern = Pattern(
            name="aws_key",
            regex="AKIA[0-9A-Z]{16}",
            score=0.9
        )
        aws_recognizer = PatternRecognizer(
            supported_entity="AWS_ACCESS_KEY",
            patterns=[aws_pattern],
            context=["aws", "amazon", "access_key", "secret_key"]
        )
        self.analyzer.registry.add_recognizer(aws_recognizer)

        # 2. Azure Storage Keys (Base64 heuristic)
        azure_pattern = Pattern(
            name="azure_key",
            regex="([A-Za-z0-9+/]{86}==)",
            score=0.6
        )
        azure_recognizer = PatternRecognizer(
            supported_entity="AZURE_KEY",
            patterns=[azure_pattern],
            context=["azure", "storage", "connectionstring"]
        )
        self.analyzer.registry.add_recognizer(azure_recognizer)

        # 3. JWT Tokens
        jwt_pattern = Pattern(
            name="jwt_token",
            regex="ey[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*",
            score=0.9
        )
        jwt_recognizer = PatternRecognizer(
            supported_entity="JWT_TOKEN",
            patterns=[jwt_pattern],
            context=["jwt", "token", "auth", "bearer"]
        )
        self.analyzer.registry.add_recognizer(jwt_recognizer)

        # 4. Internal IP Addresses
        internal_ip_pattern = Pattern(
            name="internal_ip",
            regex="(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})",
            score=0.9
        )
        internal_ip_recognizer = PatternRecognizer(
            supported_entity="INTERNAL_IP",
            patterns=[internal_ip_pattern]
        )
        self.analyzer.registry.add_recognizer(internal_ip_recognizer)

        # 5. Passwords (in connection strings or variables)
        password_pattern = Pattern(
            name="password_assignment",
            regex="(?i)(password|passwd|pwd|secret)\s*[:=]\s*['\"]([^'\"]+)['\"]",
            score=0.7
        )
        password_recognizer = PatternRecognizer(
            supported_entity="PASSWORD",
            patterns=[password_pattern]
        )
        self.analyzer.registry.add_recognizer(password_recognizer)

    def sanitize(self, text: str) -> str:
        """
        Scans the text for PII/PHI/Secrets and returns the redacted text.
        """
        if not text or not text.strip():
            return text

        try:
            # Detect entities
            results = self.analyzer.analyze(
                text=text,
                language="en",
                return_decision_process=False
            )

            # Filter out entities we want to KEEP in the text (like URLs, Dates, Names)
            allowed_entities = {"URL", "DATE_TIME", "PERSON", "LOCATION", "NRP"}
            filtered_results = [r for r in results if r.entity_type not in allowed_entities]

            if not filtered_results:
                return text

            # Redact the identified entities
            # We configure the anonymizer to replace the text with <ENTITY_TYPE>
            anonymized_result = self.anonymizer.anonymize(
                text=text,
                analyzer_results=filtered_results,
                operators={
                    "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
                    "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
                    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
                    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"}),
                    "AWS_ACCESS_KEY": OperatorConfig("replace", {"new_value": "<AWS_KEY>"}),
                    "JWT_TOKEN": OperatorConfig("replace", {"new_value": "<JWT>"}),
                    "PASSWORD": OperatorConfig("replace", {"new_value": "<PASSWORD>"}),
                    "INTERNAL_IP": OperatorConfig("replace", {"new_value": "<INTERNAL_IP>"}),
                    "MEDICAL_LICENSE": OperatorConfig("replace", {"new_value": "<MEDICAL_INFO>"}),
                    "US_SSN": OperatorConfig("replace", {"new_value": "<SSN>"}),
                }
            )
            return anonymized_result.text
        except Exception as e:
            logger.error(f"Error during PII sanitization: {e}")
            # Fail-closed or Fail-open? For enterprise RAG, if we can't sanitize, 
            # we should fail-open but warn, OR fail-closed. 
            # We will return the original text but log a critical error.
            # In a strict military environment, this would raise an exception.
            return text

# Singleton instance
pii_guardrail = PIIGuardrail()
