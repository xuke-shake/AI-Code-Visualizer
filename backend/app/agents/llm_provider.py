import os
from pathlib import Path


def _load_backend_env() -> None:
    """Load backend/.env into os.environ."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    backend_dir = Path(__file__).resolve().parents[2]
    env_path = backend_dir / ".env"

    if env_path.exists():
        load_dotenv(env_path, override=True)


_load_backend_env()


class LLMProvider:
    """OpenAI-compatible LLM provider, compatible with DeepSeek."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")

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
            timeout=30.0,
        )

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                stream=False,
            )

            content = response.choices[0].message.content or ""
            return content.strip()

        except Exception as exc:
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc