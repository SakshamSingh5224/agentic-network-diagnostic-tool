"""Custom Groq language-model component for Langflow.

Groq exposes an OpenAI-compatible API, so this wraps langchain_openai's ChatOpenAI
and points it at Groq's endpoint. Model name is free text (e.g. openai/gpt-oss-120b).
"""
from lfx.base.models.model import LCModelComponent
from lfx.field_typing import LanguageModel
from lfx.io import FloatInput, SecretStrInput, StrInput


class GroqModelComponent(LCModelComponent):
    display_name = "Groq (OpenAI-compatible)"
    description = "Chat model served by Groq. Connect its Language Model output to the Agent."
    icon = "Groq"
    name = "GroqCompatibleModel"

    inputs = [
        *LCModelComponent.get_base_inputs(),
        SecretStrInput(
            name="groq_api_key",
            display_name="Groq API Key",
            info="Starts with gsk_. Best stored as a Global Variable (e.g. GROQ_API_KEY).",
            required=True,
        ),
        StrInput(
            name="model_name",
            display_name="Model Name",
            value="openai/gpt-oss-120b",
            info="Any Groq model id that supports tool calling.",
        ),
        StrInput(
            name="base_url",
            display_name="Base URL",
            value="https://api.groq.com/openai/v1",
            advanced=True,
        ),
        FloatInput(name="temperature", display_name="Temperature", value=0.1, advanced=True),
    ]

    def build_model(self) -> LanguageModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.model_name,
            api_key=self.groq_api_key,
            base_url=self.base_url,
            temperature=self.temperature,
            streaming=self.stream,
        )
