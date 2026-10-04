# -*- coding: utf-8 -*-
# 追加 P032 到掉坑笔记（用 Python UTF-8 追加，避免 PowerShell 中文编码坑）
from pathlib import Path

p = Path(r"e:\LLM\LectureLearnLoop\docs\掉坑笔记\掉坑笔记.md")
entry = """
---

### 【P032】2026-10-02 桥端点响应契约错配：后端成功、前端永远弹"未知错误"（白页）

**问题描述**：AI 练习助手"开始新练习"给测试账号充值后，LLM 真实调用成功（llm_calls 日志有完整响应、HTTP 200），但前端仍弹"生成新练习失败: 未知错误"，练习面板停留空白（用户看到的"白页"）。

**根本原因**：双层 success 包装错配。`_ok(x)` 固定产生 `{success:true, data:x}`；api.js `req()` 只检查**顶层** `j.success===false` 后 `return j.data`（unwrap 一层）。而 base.html 等旧 Qt 页面对桥方法的期望形状是 unwrap 后**内层还有** `{success:true, data:{...}}`（旧 Qt slot 直接返回单层 JSON）。`/api/practice/new` 成功分支返回的内层是裸载荷 `{id, question...}` 没有 success 字段 → 前端 `result.success` undefined → 恒走失败分支，且 `result.error` 不存在 → 文案只剩"未知错误"。失败分支（如积分不足）因带内层 success:false + error 反而显示正常，掩盖了成功分支的断链。

**解决方案**：后端成功分支补齐契约 `_ok({"success": True, "data": {...}, **billing})`（与 getPracticeHistory 等既有桥方法一致）；外层 except 的 `str(e)` 为空时兜底 `f"未知异常: {type(e).__name__}"`；新增 tests/test_practice_new_contract.py 打桩 `_llm_call` 锁住四种形状（成功/LLM异常兜底/积分不足/空异常兜底）。

**预防措施**：
1. 新增/修改 routes_bridge 端点时，必须先 grep 前端消费代码（base.html / api.js bridgeFn），确认它对 unwrap 后内层形状的判定字段（`result.success` / `result.data` / 平铺字段），后端按消费方期望返回，禁止"秀形状"。
2. 排查"前端失败但后端日志成功"类问题，第一步直接看 HTTP 响应体全文（形状断链不需要复现环境即可定位）。
3. 计费附带字段（credits_deducted 等）必须放内层顶层（billingHook 只 pick 到 j.data 层），已用测试负面断言锁死。
"""
with open(p, "a", encoding="utf-8") as f:
    f.write(entry)
print("appended", len(entry))
