"""测试 31：`degraded:scores_missing`，判据下沉到维度级（CN-011）。

**本条要防的不是「LLM 没给 scores」这个显眼形态，是它的隐蔽变体。**

`dim()` 是逐维取默认值的，所以漏 1 维与漏 4 维产生**完全相同的伪 0**。而
整体缺失（四维全 0）反而是最容易被发现的那种——部分缺失才真正静默：三维
正常、一维伪 0，加权后只是「这条新闻分数偏低一点」，落在正常分布内，
**无论消费侧部署多少监控都发现不了它**。故产生侧标记是唯一可行的检出点。

判定收归 `_clamp_score` 自身报告（Developer 末票中①）：在它之外另写一套
「什么算有效 score」，两套得永远同步，而分叉时不会有任何信号。
"""
from __future__ import annotations

import pytest

from agent_hub.graphs.news_l1 import _clamp_score
from agent_hub.schemas import L1Input
from agent_hub.tasks import run_task
from tests.test_news_l1 import FakeClient, NullTools, _payload, make_parsed


def make_input() -> L1Input:
    return L1Input(**_payload())

_TAG = "degraded:scores_missing"


async def _processing(parsed) -> list[str]:
    result = await run_task("news-l1", "run_t31", make_input(),
                            client=FakeClient(parsed=parsed), tools=NullTools())
    assert result.output is not None
    return list(result.output.tags.processing)


# --- _clamp_score 的有效性判定（唯一定义处）---
@pytest.mark.parametrize(
    "value, expected",
    [
        (4, (4, True)),
        (0, (0, True)),          # 真 0：LLM 确实打了 0 分
        (9, (5, True)),          # 越界仍是有效表态，钳制到上限
        (None, (0, False)),      # score 为 null
        ("high", (0, False)),    # 类型非法
        (True, (0, False)),      # bool 是 int 子类，int(True)=1 会被当成 1 分收下
    ],
    ids=["valid", "true_zero", "clamped", "null", "wrong_type", "bool"],
)
def test_clamp_score_reports_validity(value, expected):
    assert _clamp_score(value) == expected


# --- 整体缺失：Developer 联调实测到的形态（只是特例）---
async def test_whole_scores_missing_is_tagged():
    processing = await _processing(make_parsed(scores={}))
    assert _TAG in processing


async def test_scores_key_absent_is_tagged():
    parsed = make_parsed()
    parsed.pop("scores")
    assert _TAG in await _processing(parsed)


# --- 部分缺失：本条的重点，双方现有判据都抓不到 ---
async def test_single_missing_dimension_is_tagged():
    """漏 1 维与漏 4 维产生同样的伪 0，但**双方现有判据都是按「四维全 0 且
    reason 全空」写的，完全抓不到它**。"""
    scores = make_parsed()["scores"]
    del scores["impact"]
    processing = await _processing(make_parsed(scores=scores))
    assert _TAG in processing


# --- 「是 dict 但仍伪 0」的三种形态：判据若只判 isinstance(dict) 会全部放行 ---
@pytest.mark.parametrize(
    "bad_dim",
    [
        {"reason": "有理由但没给分"},        # 有对象、无 score 键
        {"score": "high", "reason": "r"},    # score 类型非法
        {"score": None, "reason": "r"},      # score 为 null
    ],
    ids=["no_score_key", "wrong_type", "null_score"],
)
async def test_dict_shaped_but_still_pseudo_zero_is_tagged(bad_dim):
    """**这三种比整体缺失更可能发生**——prompt 里给了 schema，LLM 的结构骨架
    通常是对的，错的往往是某个值的类型或空值。它们全都是 dict，
    `not isinstance(..., dict)` 一个也拦不住。"""
    scores = make_parsed()["scores"]
    scores["clarity"] = bad_dim
    assert _TAG in await _processing(make_parsed(scores=scores))


# --- 反向：判据不能过宽 ---
async def test_complete_scores_are_not_tagged():
    """四维齐全时**不得**加标记——判据过宽会把正常条目也标上，标记随即失去意义。"""
    assert _TAG not in await _processing(make_parsed())


async def test_genuine_zero_is_not_tagged():
    """LLM 真的打了 0 分是**有效表态**，不是缺失。

    这条是本组最关键的反向用例：伪 0 与真 0 的取值完全相同，把真 0 也标上
    就等于没有区分能力。
    """
    scores = {n: {"score": 0, "reason": f"{n} 确实不值分"}
              for n in ("timeliness", "impact", "confidence", "clarity")}
    assert _TAG not in await _processing(make_parsed(scores=scores))


# --- 标记形态与日志明细（变更 2）---
async def test_tag_stays_single_segment_while_detail_goes_to_log():
    """标记保持 `degraded:{name}` 单段（对方消费代码可能按全等或前缀匹配），
    缺哪几维只进 degradations 日志。

    **变更 2 的两句话在实现上原本是冲突的**——`degradations` 既是日志来源、
    又直接转成标记，「明细进 degradations」等于「明细进标记」。故生成标记时
    只取冒号前一段。
    """
    scores = make_parsed()["scores"]
    del scores["impact"]
    del scores["clarity"]
    result = await run_task("news-l1", "run_t31", make_input(),
                            client=FakeClient(parsed=make_parsed(scores=scores)),
                            tools=NullTools())

    processing = list(result.output.tags.processing)
    assert _TAG in processing
    assert not any(t.startswith(_TAG + ":") for t in processing), "标记不得带第三段"

    detail = [d for d in result.degradations if d.startswith("scores_missing:")]
    assert detail, "缺失明细须进 degradations 日志"
    assert "impact" in detail[0] and "clarity" in detail[0]
