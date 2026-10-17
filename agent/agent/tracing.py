"""Optional Langfuse Cloud tracing. Off unless both LANGFUSE keys are set."""

from langchain_core.callbacks import BaseCallbackHandler

from agent.config import get_settings


def get_callbacks() -> list[BaseCallbackHandler]:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return []
    # The Langfuse SDK reads LANGFUSE_PUBLIC_KEY / SECRET_KEY / HOST from the environment.
    from langfuse.langchain import CallbackHandler

    return [CallbackHandler()]
