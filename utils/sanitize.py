import re

def strip_reasoning(text: str) -> str:
    """Removes <thinking>...</thinking> blocks to prevent context pollution and cache leakage."""
    if not text:
        return text
    return re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL).strip()
