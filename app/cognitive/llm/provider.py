"""
Solasta — LLM Provider Factory

Polymorphic provider switching with automatic fallback.
Requests LLMs by trait ("reasoning", "fast") rather than by brand.
Includes timeout enforcement, retry logic, and structured output parsing.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Type

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import LLMProvider, settings
from app.core.logging import get_logger
from app.schemas.models import AgentLog

logger = get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Provider Factory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _create_provider(provider: LLMProvider) -> BaseChatModel:
    """Instantiate the appropriate LangChain chat model."""

    if provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=0.2,
            timeout=settings.llm_timeout_seconds,
        )

    elif provider == LLMProvider.GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=0.2,
            timeout=settings.llm_timeout_seconds,
        )

    elif provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0.2,
            timeout=settings.llm_timeout_seconds,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Fallback-Aware LLM Gateway
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class LLMGateway:
    """
    Central LLM routing layer with automatic fallback.

    Usage:
        gateway = LLMGateway()
        result = await gateway.generate(prompt="...", system="...")
        structured = await gateway.generate_structured(prompt="...", schema=MyModel)
    """

    def __init__(self):
        self._fallback_chain: List[LLMProvider] = [
            settings.llm_primary_provider,
            settings.llm_fallback_provider,
            settings.llm_tertiary_provider,
        ]
        self._providers: Dict[LLMProvider, BaseChatModel] = {}
        self._active_provider: Optional[LLMProvider] = None

    def _get_or_create(self, provider: LLMProvider) -> BaseChatModel:
        if provider not in self._providers:
            self._providers[provider] = _create_provider(provider)
        return self._providers[provider]

    async def generate(
        self,
        prompt: str,
        system: str = "You are a helpful AI assistant.",
        goal_id: str = "",
        agent_type: str = "general",
    ) -> tuple[str, AgentLog]:
        """
        Generate a response with automatic provider fallback.
        Returns (response_text, agent_log).
        """
        last_error = None

        for provider in self._fallback_chain:
            try:
                llm = self._get_or_create(provider)
                self._active_provider = provider

                messages = [SystemMessage(content=system), HumanMessage(content=prompt)]

                start = time.perf_counter()

                # Proactive delay for Gemini to prevent hitting the 15 RPM free tier limit
                if provider == LLMProvider.GEMINI:
                    await asyncio.sleep(4.0)

                response = None
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = await asyncio.wait_for(
                            llm.ainvoke(messages),
                            timeout=settings.llm_timeout_seconds,
                        )
                        break
                    except Exception as invoke_err:
                        err_str = str(invoke_err).lower()
                        if "429" in err_str or "resourceexhausted" in err_str or "too many requests" in err_str:
                            if attempt < max_retries - 1:
                                delay_time = 5 * (attempt + 1)
                                logger.warning("rate_limit_hit", provider=provider.value, msg=f"Delaying {delay_time}s... (attempt {attempt+1}/{max_retries})")
                                await asyncio.sleep(delay_time)
                                continue
                        raise invoke_err

                latency = int((time.perf_counter() - start) * 1000)

                text = response.content if hasattr(response, "content") else str(response)

                log = AgentLog(
                    goal_id=goal_id,
                    agent_type=agent_type,
                    provider=provider.value,
                    model=self._get_model_name(provider),
                    prompt_summary=prompt[:200],
                    response_summary=text[:300],
                    tokens_in=response.usage_metadata.get("input_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0,
                    tokens_out=response.usage_metadata.get("output_tokens", 0) if hasattr(response, "usage_metadata") and response.usage_metadata else 0,
                    latency_ms=latency,
                )

                logger.info(
                    "llm_success",
                    provider=provider.value,
                    latency_ms=latency,
                    agent_type=agent_type,
                )
                return text, log

            except Exception as e:
                last_error = e
                # Ensure we capture the full error message
                error_str = str(e) if str(e) else repr(e)
                logger.warning(
                    "llm_provider_failed",
                    provider=provider.value,
                    error=error_str,
                    error_type=type(e).__name__,
                    fallback_next=True,
                )
                continue

        error_detail = str(last_error) if last_error and str(last_error) else repr(last_error)
        error_msg = f"All LLM providers failed. Last error: {error_detail}"
        logger.error("llm_all_providers_failed", error=error_msg)

        log = AgentLog(
            goal_id=goal_id,
            agent_type=agent_type,
            provider="none",
            model="none",
            prompt_summary=prompt[:200],
            response_summary="",
            error=error_msg,
        )
        raise RuntimeError(error_msg)

    def _sanitize_json_response(self, text: str) -> str:
        """
        Strip conversational preamble/postamble and markdown fences.
        Returns only the JSON object between first '{' and last '}'.
        """
        import re

        cleaned = text.strip()

        # Remove markdown code fences (```json ... ``` or ``` ... ```)
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        fence_match = re.search(fence_pattern, cleaned, re.IGNORECASE)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        # Find first '{' and last '}' to extract JSON object
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")

        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            cleaned = cleaned[first_brace : last_brace + 1]

        return cleaned

    async def generate_structured(
        self,
        prompt: str,
        schema: Type[BaseModel],
        system: str = "You are a helpful AI assistant. Always respond with valid JSON.",
        goal_id: str = "",
        agent_type: str = "general",
        retries: int = 2,
    ) -> tuple[Any, AgentLog]:
        """
        Generate a structured response conforming to a Pydantic schema.
        Automatically retries with error feedback on parse failure.
        """
        parser = JsonOutputParser(pydantic_object=schema)
        format_instructions = parser.get_format_instructions()

        full_prompt = f"{prompt}\n\n{format_instructions}"

        for attempt in range(retries + 1):
            text, log = await self.generate(
                prompt=full_prompt,
                system=system,
                goal_id=goal_id,
                agent_type=agent_type,
            )
            try:
                sanitized = self._sanitize_json_response(text)
                parsed = parser.parse(sanitized)
                return parsed, log
            except Exception as parse_err:
                if attempt < retries:
                    full_prompt = (
                        f"{prompt}\n\n{format_instructions}\n\n"
                        f"Your previous response was invalid JSON. Error: {parse_err}\n"
                        f"Previous response: {text[:500]}\n"
                        f"Please fix and respond with ONLY valid JSON."
                    )
                    logger.warning(
                        "structured_parse_retry",
                        attempt=attempt + 1,
                        error=str(parse_err),
                    )
                else:
                    log.error = f"Structured output parse failed after {retries + 1} attempts: {parse_err}"
                    raise

        raise RuntimeError("Unreachable")

    def _get_model_name(self, provider: LLMProvider) -> str:
        if provider == LLMProvider.OLLAMA:
            return settings.ollama_model
        elif provider == LLMProvider.GEMINI:
            return settings.gemini_model
        elif provider == LLMProvider.OPENAI:
            return settings.openai_model
        return "unknown"

    @property
    def active_provider_name(self) -> str:
        return self._active_provider.value if self._active_provider else "none"


# Singleton
llm_gateway = LLMGateway()
