import os
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain_groq import ChatGroq
from config.settings import settings

def get_llm(temperature=0.0, max_tokens=None, agent_name=None, **kwargs):
    """
    Factory function to return the appropriate LLM based on LLM_PROVIDER in .env.
    Supports: "azure", "github", "groq"
    """
    provider = settings.LLM_PROVIDER.lower()
    
    if provider == "github":
        return ChatOpenAI(
            model=getattr(settings, "GITHUB_MODEL", "gpt-4o"), # Switched to gpt-4o because gpt-4o-mini limit is hit
            api_key=settings.GITHUB_TOKEN,
            base_url="https://models.inference.ai.azure.com",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=5,
            **kwargs
        )
    elif provider == "groq":
        keys = [k.strip() for k in settings.GROQ_API_KEYS.split(",") if k.strip()]
        if keys:
            if agent_name:
                import hashlib
                idx = int(hashlib.md5(agent_name.encode()).hexdigest(), 16) % len(keys)
                api_key = keys[idx]
            else:
                import random
                api_key = random.choice(keys)
        else:
            api_key = None
            
        return ChatGroq(
            model="llama-3.1-8b-instant",  # Fallback groq model
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=5,
            **kwargs
        )
    else:
        # Default to Azure OpenAI
        return AzureChatOpenAI(
            azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=5,
            **kwargs
        )
