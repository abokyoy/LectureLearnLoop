# 检查 :6001 返回模板是否含评审 Minor 修复特征（判断是否必须重启）
import json
import urllib.request

TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
req = urllib.request.Request("http://127.0.0.1:6001/fragments/online_course_notes",
                             headers={"Authorization": "Bearer " + TOKEN})
body = urllib.request.urlopen(req).read().decode("utf-8")
html = json.loads(body).get("data", "")
checks = {
    "len": len(html),
    "minor2_MAXB": "var MAXB = 50 * 1024 * 1024" in html,
    "minor3_target_snapshot": "var target = _impTargetPath || 'vault'" in html,
    "minor4_timer_guard": "if (!document.getElementById('file-tree')) { clearInterval(timer); return; }" in html,
    "minor5_css": "#file-structure.collapsed #import-status-bar" in html,
}
print(json.dumps(checks, indent=1))
