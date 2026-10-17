"""The only place that talks to the LLM provider. Tests monkeypatch `structured_call`."""

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from agent.config import get_settings


class LLMNotConfiguredError(RuntimeError):
    pass


def structured_call[T: BaseModel](schema: type[T], system: str, user: str) -> T:
    """Call the OpenAI-compatible endpoint and parse the reply into `schema`."""
    settings = get_settings()
    if not (settings.openai_base_url and settings.llm_model):
        raise LLMNotConfiguredError("Set OPENAI_BASE_URL and LLM_MODEL to run the agent")
    model = ChatOpenAI(
        base_url=settings.openai_base_url,
        # Some local OpenAI-compatible servers accept any key; the client still requires one.
        api_key=settings.openai_api_key or "not-set",
        model=settings.llm_model,
        temperature=0,
    )
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
