"""内部 task registry / dispatch（AC-9）。

对外 HTTP 契约保持 `POST /v1/runs/news-l1` 不变；本模块只在代码层按
task_type 分发到对应处理图，使未来新增任务类型注册新图而非改入口框架。
v0.1 只注册 news-l1，不暴露通用路由、不新增 caller/task_type 传输字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from agent_hub.graphs.news_l1 import init_news_l1_state, news_l1_graph
from agent_hub.llm.client import AIClient
from agent_hub.schemas import L1Input, L1Output, ToolSummary


@dataclass
class TaskSpec:
    task_type: str
    input_model: type[BaseModel]
    graph: object
    init_state: Callable


@dataclass
class TaskRunResult:
    output: L1Output | None
    tool_summary: ToolSummary
    needs_context: bool = False
    degradations: list[str] = field(default_factory=list)
    error: str | None = None


class UnknownTaskError(KeyError):
    """请求了未注册的内部 task_type。不对外暴露为新 HTTP 路由。"""


_REGISTRY: dict[str, TaskSpec] = {}


def register_task(spec: TaskSpec) -> None:
    _REGISTRY[spec.task_type] = spec


def get_task(task_type: str) -> TaskSpec:
    try:
        return _REGISTRY[task_type]
    except KeyError as exc:
        raise UnknownTaskError(task_type) from exc


def run_task(
    task_type: str, run_id: str, inp: BaseModel, client: AIClient
) -> TaskRunResult:
    spec = get_task(task_type)
    state = spec.init_state(run_id, inp, client)
    final = spec.graph.invoke(state)
    output = final.get("output")
    return TaskRunResult(
        output=output,
        tool_summary=final.get("tool_summary") or ToolSummary(),
        needs_context=bool(final.get("needs_context")),
        degradations=list(final.get("degradations") or []),
        error=None if output is not None else _summarize_errors(final.get("errors")),
    )


def _summarize_errors(errors) -> str:
    if not errors:
        return "processing failed"
    return "; ".join(f"{e.step}:{e.kind}" for e in errors)


register_task(
    TaskSpec(
        task_type="news-l1",
        input_model=L1Input,
        graph=news_l1_graph,
        init_state=init_news_l1_state,
    )
)
