import os
from openai import OpenAI
#配置和调用大模型

class LLMProvider:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = "ep-20260518195441-rxvr7"):
        # 初始化大模型客户端
        self.api_key = api_key or os.getenv("LLM_API_KEY", "你的api key")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "你的uri")
        self.model = model

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> str:
        """统一的文本生成接口"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature,  # 较低的随机度保证逻辑图生成的稳定性
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {str(e)}")