"""The only place that talks to the LLM provider. Tests monkeypatch `structured_call`."""

import os

from pydantic import BaseModel

from agent.config import get_settings


class LLMNotConfiguredError(RuntimeError):
    pass


def get_llm():
    """Return configured Chat model based on LLM_TYPE (gemini vs openai)."""
    settings = get_settings()
    llm_type = (settings.llm_type or "openai").strip().lower()

    if llm_type == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = (
            settings.gemini_api_key
            or settings.google_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or settings.openai_api_key
        )
        if not api_key:
            raise LLMNotConfiguredError(
                "Set GEMINI_API_KEY or GOOGLE_API_KEY to run the agent with Gemini"
            )
        model_name = settings.llm_model or "gemini-2.0-flash"
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=0,
        )

    # Default: langchain_openai
    from langchain_openai import ChatOpenAI

    if not (settings.openai_base_url and settings.llm_model):
        raise LLMNotConfiguredError("Set OPENAI_BASE_URL and LLM_MODEL to run the agent")
    return ChatOpenAI(
        base_url=settings.openai_base_url,
        # Some local OpenAI-compatible servers accept any key; the client still requires one.
        api_key=settings.openai_api_key or "not-set",
        model=settings.llm_model,
        temperature=0,
    )


def structured_call[T: BaseModel](schema: type[T], system: str, user: str) -> T:
    """Call the configured LLM endpoint and parse the reply into `schema`."""
    settings = get_settings()
    model = get_llm()
    # json_schema by default; LLM_STRUCTURED_METHOD=function_calling for providers that reject it.
    # Callbacks (Langfuse) come from the graph's config through LangChain's context propagation.
    result = model.with_structured_output(schema, method=settings.llm_structured_method).invoke(
        [("system", system), ("user", user)]
    )
    if result is None:
        # function_calling returns None when the model answers in prose instead of calling the tool.
        raise ValueError(
            f"LLM returned no {schema.__name__}; try LLM_STRUCTURED_METHOD=json_schema"
        )
    return result
