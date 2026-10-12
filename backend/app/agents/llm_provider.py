from __future__ import annotations
from dataclasses import dataclass

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class LLMResult:
    content: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider:
    """OpenAI-compatible LLM provider, compatible with DeepSeek."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.api_key = api_key if api_key is not None else self.settings.llm_api_key
        self.base_url = (base_url or self.settings.llm_base_url).rstrip("/")
        self.model = model or self.settings.llm_model

        if self.base_url:
            self.base_url = self.base_url.rstrip("/")

        # 避免误写成 https://api.deepseek.com/anthropic
        if self.base_url.endswith("/anthropic"):
            self.base_url = self.base_url.removesuffix("/anthropic")

        if not self.api_key:
            raise RuntimeError("缺少 LLM_API_KEY，已跳过大模型生成")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("缺少 openai 依赖，请先执行 python -m pip install openai") from exc

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.settings.llm_timeout_seconds,
            max_retries=0,
        )

    def close(self) -> None:
        self.client.close()

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> LLMResult:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=self.settings.llm_max_output_tokens,
                stream=False,
                timeout=self.settings.llm_timeout_seconds,
            )

            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            return LLMResult(content.strip(),
                             getattr(usage, "prompt_tokens", None),
                             getattr(usage, "completion_tokens", None))

        except Exception as exc:
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc
