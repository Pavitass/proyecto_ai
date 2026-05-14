from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from helpdesk_app.config import (
    CHAT_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    GOOGLE_API_KEY,
    LLM_TEMPERATURE,
    use_deepseek_llm,
)


def get_chat_model() -> BaseChatModel:
    """DeepSeek (OpenAI-compatible) o Gemini según HELPDESK_LLM / claves en .env."""
    if use_deepseek_llm():
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("HELPDESK_LLM=deepseek requiere DEEPSEEK_API_KEY en .env.")
        return ChatOpenAI(
            model=CHAT_MODEL,
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            temperature=LLM_TEMPERATURE,
        )
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "Configura GOOGLE_API_KEY (Gemini) o DEEPSEEK_API_KEY con HELPDESK_LLM=deepseek."
        )
    return ChatGoogleGenerativeAI(
        model=CHAT_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=LLM_TEMPERATURE,
    )
