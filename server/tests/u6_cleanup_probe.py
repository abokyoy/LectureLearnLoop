# 清理 u4/u5 验证残留：测试导入的 md + 两个空"新文件夹"目录（仅测试账号 vault）
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VAULT = r"e:\LLM\LectureLearnLoop\server\data\vault\940ee3cf7c33"
removed = []
for name in ["u4_import_probe.md", "u4_import_probe_1.md"]:
    p = os.path.join(VAULT, name)
    if os.path.exists(p):
        os.remove(p)
        removed.append(name)
for d in os.listdir(VAULT):
    full = os.path.join(VAULT, d)
    if os.path.isdir(full) and d.startswith("新文件夹") and not os.listdir(full):
        shutil.rmtree(full)
        removed.append("dir:" + d)
print("REMOVED:", removed or "nothing")
