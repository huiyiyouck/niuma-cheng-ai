"""AC-2.2 静态判据：处理核心零数据源概念（设计 §1.3、§8 测试 13）。

AC-2.2 的判据被 CN-003 拆成两条，因为原前半句「同一份处理核心……代码完全
相同」是**同义反复**——只要不把核心复制成两份就必然成立，不可证伪：
- **静态（本测试）**：处理核心内 grep 不到数据源概念词，可自动化；
- **动态**：两条控制流各跑通一条真实用例（HTTP 由 test_news_l1 覆盖，
  DB 由测试 20 端到端覆盖）。

这条守的是依赖方向：`worker/` 与 `sources/` 依赖处理核心，反之不成立。
一旦有人图省事在 graph 里直接读库列名，本测试立刻失败。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src" / "agent_hub"

# 处理核心：不得出现任何数据源概念
_CORE_PATHS = ["tasks.py", "graphs", "llm"]

# 库表名 / 列名 / 拉取型控制流概念
_FORBIDDEN = re.compile(
    r"\b(raw_items|processed_news|news_positions|l1_status|l1_attempt|"
    r"source_item_url|l0_label|locked_by|locked_at|run_after|max_attempts)\b"
)


def _iter_py(path: Path):
    if path.is_file():
        yield path
    else:
        yield from path.rglob("*.py")


@pytest.mark.parametrize("rel", _CORE_PATHS)
def test_core_has_no_datasource_concepts(rel: str):
    hits = []
    for py in _iter_py(_SRC / rel):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line):
                hits.append(f"{py.relative_to(_SRC)}:{lineno}: {line.strip()}")
    assert not hits, "处理核心出现数据源概念词，依赖方向被破坏：\n" + "\n".join(hits)


@pytest.mark.parametrize("rel", _CORE_PATHS)
def test_core_does_not_import_datasource_layers(rel: str):
    """处理核心不得 import `sources/` 或 `worker/`。

    `ItemBudget` 因此放在 `agent_hub/budget.py` 顶层而非设计写的
    `worker/budget.py`——它要随 L1State 流经 graph 各节点，定义在 worker/ 下
    会让处理核心反向 import 拉取型控制流的包。
    """
    bad = re.compile(r"^\s*(from|import)\s+agent_hub\.(sources|worker)\b")
    hits = []
    for py in _iter_py(_SRC / rel):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if bad.match(line):
                hits.append(f"{py.relative_to(_SRC)}:{lineno}: {line.strip()}")
    assert not hits, "处理核心反向依赖数据源层：\n" + "\n".join(hits)
