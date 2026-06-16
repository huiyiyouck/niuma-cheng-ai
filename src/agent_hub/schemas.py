"""平台 ↔ Agent Hub 跨服务契约（来自 niuma-cheng-xiaobao 提案 §6/§7）。

L1Input / L1Output 与新闻平台 server 端保持一致，是跨服务稳定契约，
改动需两侧同步（见提案 §12.5 异步工程问题 #6：tasks 为业务真源，run 仅处理证据）。

注意：评分加权 score_total 留在新闻平台（§12.6），本服务只产四维 score + reason。
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RunOptions(BaseModel):
    max_tool_calls: int = 4
    timeout_ms: int = 180000


class L1Input(BaseModel):
    source_identity: str
    domain_tags: list[str] = Field(default_factory=list)
    raw_content: dict = Field(default_factory=dict)
    raw_text: str = ""
    kb_results: list[dict] = Field(default_factory=list)
    link_content: Optional[str] = None
    search_summary: Optional[str] = None
    options: RunOptions = Field(default_factory=RunOptions)


class ScoreDimension(BaseModel):
    score: int  # 0-5
    reason: str = ""


class ScoreDimensions(BaseModel):
    timeliness: ScoreDimension
    impact: ScoreDimension
    confidence: ScoreDimension
    clarity: ScoreDimension


class Tags(BaseModel):
    domain: list[str] = Field(default_factory=list)
    entity: list[str] = Field(default_factory=list)
    event: list[str] = Field(default_factory=list)
    content_type: list[str] = Field(default_factory=list)
    processing: list[str] = Field(default_factory=list)


class L1Output(BaseModel):
    title: str
    summary: str
    translation: dict = Field(default_factory=dict)  # {"zh": "..."}
    context: list = Field(default_factory=list)
    analysis: Optional[str] = None
    score_dimensions: ScoreDimensions
    tags: Tags = Field(default_factory=Tags)
    needs_context: bool = False


class ToolSummary(BaseModel):
    web_search: int = 0
    link_read: int = 0
    kb_search: int = 0


class RunResponse(BaseModel):
    run_id: str
    status: Literal["succeeded", "failed"]
    elapsed_ms: int
    tool_summary: ToolSummary
    output: Optional[L1Output] = None
    error: Optional[str] = None
