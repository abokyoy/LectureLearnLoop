# -*- coding: utf-8 -*-
# 追加掉坑笔记 P029-P031
p = r"e:\LLM\LectureLearnLoop\docs\掉坑笔记\掉坑笔记.md"
add = """
### P029（2026-10-02）沙箱内重启 Flask 服务：看不到端口、杀不掉进程、子进程静默死亡

**现象**：脚本在沙箱 PowerShell 里执行 `Get-NetTCPConnection -LocalPort 6001` 返回空（实际有监听）、Stop-Process 杀不掉目标进程、Start-Process 拉起的 python 几秒后消失（PORT_READY=False / PROCESS_ALIVE=False），一度误判"服务本来就挂了"。

**根本原因**：命令沙箱隔离了网络命名空间视图与进程对象，跨边界不可见也不可操作；沙箱内启动的子进程随命令结束被回收。

**解决方案**：涉及"杀进程/拉起常驻服务"的脚本一律以沙箱外权限执行（required_permissions=all），并保留"端口检测 + 响应内容特征断言"双重确认（见 P027 延伸：重启后 fetch /fragments/<id> 查新代码字符串是否出现，不能只信命令跑完）。

**教训**：环境判定异常（"端口空闲"与实际矛盾）先怀疑执行边界，不要基于沙箱内视图下结论、更不要在此基础上连环操作。

---

### P030（2026-10-02）SPA 片段脚本链竞态：固定 sleep 误判尾块函数 undefined

**现象**：Playwright 进入学页后固定等 3s，`typeof window.handlePractice` 为 undefined，疑似尾块未执行；另一会话等 4s + 中间做过交互则一切正常。

**根本原因**：updateContentArea 的 execScript 链对**外部脚本逐个 onload 串行**（批6修复），学页片段外部依赖多（hljs/mermaid/jstree 等），磁盘缓存冷时整链跨越数秒，尾块（四期D组统一右键基础设施）最后才求值。

**解决方案**：验证脚本断言片段函数前，必须**轮询尾块特征**（如 `typeof window.llRunOnMenuText==='function'`）直到就绪或超时，禁止固定短 sleep 判定"函数缺失"这种假阳性。

**教训**：以"函数 undefined"作缺陷证据前，先排除脚本链未完成时序；轮询断言比等待时长更可靠。

---

### P031（2026-10-02）PowerShell Out-File 与脚本自身写同一结果文件冲突 → PermissionError

**现象**：`python tests\\u4_verify.py 2>&1 | Out-File logs\\u4_verify.txt` 报 PermissionError: 脚本内部 open(OUT,"w") 与 Out-File 占同一文件。

**解决方案**：验证脚本自写结果文件时，命令行不再管道重定向到同一路径；终端里直接跑脚本 + 事后 Get-Content 读结果。

---

"""
with open(p, "a", encoding="utf-8") as f:
    f.write(add)
print("appended")
