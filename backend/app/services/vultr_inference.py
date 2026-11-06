import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Type, TypeVar
import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger("neuroforge.vultr_inference")

T = TypeVar("T", bound=BaseModel)


class VultrInferenceError(Exception):
    """Base exception for Vultr Serverless Inference errors."""
    pass


class VultrInferenceAuthError(VultrInferenceError):
    """Raised when authentication fails (401/403 or missing API key)."""
    pass


class VultrInferenceRateLimitError(VultrInferenceError):
    """Raised when rate limits are exceeded (429)."""
    pass


class VultrInferenceUnavailableError(VultrInferenceError):
    """Raised when service is unreachable, timed out, or returning 5xx."""
    pass


class VultrInferenceFormatError(VultrInferenceError):
    """Raised when structured response cannot be parsed into the expected schema."""
    pass


class VultrInferenceModelNotFoundError(VultrInferenceError):
    """Raised when the requested model is not found or unsupported (HTTP 404/400)."""
    pass


class InferenceResponse(BaseModel):
    content: str
    parsed: Optional[Dict[str, Any]] = None
    provider: str = "Vultr Serverless Inference"
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_seconds: float


class VultrInferenceService:
    """
    Dedicated client for Vultr Serverless Inference using OpenAI-compatible chat completions.
    Adheres to Blast Radius Zero principles:
    - API keys reside solely in server-side configuration.
    - No credentials are ever passed to Docker containers or client interfaces.
    - Bounded retries and exponential backoff prevent runaway load.
    - Transparent provider attribution and safe logging.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        mock_handler: Optional[Any] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.VULTR_INFERENCE_API_KEY
        self.base_url = (base_url or settings.VULTR_INFERENCE_BASE_URL).rstrip("/")
        self.model = model or settings.VULTR_INFERENCE_MODEL or "llama-3.3-70b-instruct-fp8"
        self.timeout = timeout or settings.VULTR_INFERENCE_TIMEOUT_SECONDS
        self.max_retries = max_retries or settings.VULTR_INFERENCE_MAX_RETRIES
        self.mock_handler = mock_handler

    def is_configured(self) -> bool:
        """Check whether valid credentials are configured for Vultr Serverless Inference."""
        return bool(self.api_key and len(self.api_key.strip()) > 0)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_model: Optional[Type[T]] = None,
    ) -> InferenceResponse:
        """
        Execute chat completion against Vultr Serverless Inference.
        Handles bounded retries for transient errors and rate limits.
        """
        # If a mock handler is configured (e.g. for unit testing), use it directly
        if self.mock_handler:
            return self.mock_handler(messages, response_model=response_model)

        if not self.is_configured():
            raise VultrInferenceAuthError(
                "Vultr Serverless Inference API key is not configured. "
                "Please configure VULTR_INFERENCE_API_KEY in the server environment."
            )

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NeuroForge-Scientific-Agent/1.0",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Request JSON output when a schema is specified
        if response_model is not None:
            payload["response_format"] = {"type": "json_object"}

        start_time = time.monotonic()
        attempt = 0
        last_exception: Optional[Exception] = None

        client_timeout = httpx.Timeout(timeout=float(self.timeout), connect=10.0, read=float(self.timeout), write=10.0)

        while attempt < self.max_retries:
            attempt += 1
            try:
                logger.info(
                    f"Submitting inference request to Vultr ({self.model}), attempt {attempt}/{self.max_retries}"
                )
                with httpx.Client(timeout=client_timeout) as client:
                    resp = client.post(endpoint, json=payload, headers=headers)

                duration = round(time.monotonic() - start_time, 2)

                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise VultrInferenceFormatError("Empty completion choices returned by Vultr inference.")

                    raw_content = choices[0].get("message", {}).get("content", "")
                    usage = data.get("usage", {})

                    parsed_data = None
                    if response_model is not None:
                        parsed_data = self._extract_and_validate_json(raw_content, response_model)

                    return InferenceResponse(
                        content=raw_content,
                        parsed=parsed_data.model_dump() if parsed_data else None,
                        provider="Vultr Serverless Inference",
                        model=self.model,
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        duration_seconds=duration,
                    )

                elif resp.status_code in (401, 403):
                    raise VultrInferenceAuthError(
                        f"Authentication failed with Vultr Serverless Inference (HTTP {resp.status_code}). "
                        "Please verify your VULTR_INFERENCE_API_KEY."
                    )
                elif resp.status_code == 404:
                    raise VultrInferenceModelNotFoundError(
                        f"Vultr model '{self.model}' or endpoint not found (HTTP 404). "
                        "Please verify VULTR_INFERENCE_MODEL or VULTR_INFERENCE_BASE_URL."
                    )
                elif resp.status_code == 400:
                    raise VultrInferenceError(
                        f"Bad request sent to Vultr Serverless Inference (HTTP 400): {resp.text[:200]}"
                    )
                elif resp.status_code == 429:
                    retry_after = min(2 ** attempt, 8)
                    logger.warning(
                        f"Vultr Serverless Inference rate limit hit (HTTP 429). Retrying in {retry_after}s..."
                    )
                    time.sleep(retry_after)
                    last_exception = VultrInferenceRateLimitError(
                        "Rate limit exceeded on Vultr Serverless Inference. Bounded retries exhausted."
                    )
                    continue
                elif resp.status_code >= 500:
                    retry_after = min(2 ** attempt, 8)
                    logger.warning(
                        f"Vultr Serverless Inference upstream error (HTTP {resp.status_code}). "
                        f"Retrying in {retry_after}s..."
                    )
                    time.sleep(retry_after)
                    last_exception = VultrInferenceUnavailableError(
                        f"Vultr Serverless Inference service unavailable (HTTP {resp.status_code})."
                    )
                    continue
                else:
                    raise VultrInferenceError(
                        f"Vultr Serverless Inference returned unexpected status {resp.status_code}: {resp.text[:200]}"
                    )

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                retry_after = min(2 ** attempt, 8)
                logger.warning(f"Network error communicating with Vultr: {e}. Retrying in {retry_after}s...")
                time.sleep(retry_after)
                last_exception = VultrInferenceUnavailableError(
                    f"Network or timeout connecting to Vultr Serverless Inference: {e}"
                )
                continue

        raise last_exception or VultrInferenceError("Inference request failed after maximum bounded retries.")

    def list_models(self) -> List[str]:
        """Fetch list of available models from Vultr Serverless Inference."""
        if not self.is_configured():
            raise VultrInferenceAuthError(
                "Vultr Serverless Inference API key is not configured. Cannot list models."
            )
        endpoint = f"{self.base_url}/models"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "NeuroForge-Scientific-Agent/1.0",
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(endpoint, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            models_data = data.get("data", [])
            return [m.get("id") for m in models_data if "id" in m]
        elif resp.status_code in (401, 403):
            raise VultrInferenceAuthError(
                f"Authentication failed querying Vultr models (HTTP {resp.status_code})."
            )
        else:
            raise VultrInferenceError(
                f"Failed to query Vultr models (HTTP {resp.status_code}): {resp.text[:200]}"
            )

    def _extract_and_validate_json(self, text: str, model_cls: Type[T]) -> T:
        """Extract JSON block (even if wrapped in markdown code fences) and validate schema."""
        clean = text.strip()
        if not clean:
            raise VultrInferenceFormatError("Empty completion text returned by LLM.")

        # Extract from ```json ... ``` code fence if present
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean)
        if json_match:
            clean = json_match.group(1).strip()

        try:
            parsed = json.loads(clean)
            return model_cls.model_validate(parsed)
        except Exception as e:
            logger.error(f"Failed to validate structured JSON against {model_cls.__name__}: {e}\nRaw: {text[:300]}")
            raise VultrInferenceFormatError(
                f"LLM output could not be parsed into expected structured schema '{model_cls.__name__}': {e}"
            )

