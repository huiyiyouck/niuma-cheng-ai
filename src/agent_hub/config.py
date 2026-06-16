"""环境变量配置。

AI 推理走外部 API（OpenAI 兼容），本服务为 IO-bound 协调者（见提案 §12.3）。
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8100"))

    # LLM（OpenAI 兼容外部 API）
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    l1_llm_model: str = os.getenv("L1_LLM_MODEL", "gpt-4o-mini")
    llm_timeout_ms: int = int(os.getenv("LLM_TIMEOUT_MS", "60000"))

    # 外部搜索
    web_search_max_results: int = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))


config = Config()
