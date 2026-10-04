# 诊断4：/fragments/online_course_notes 返回内容中新旧模板特征
import json
import urllib.request

TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
req = urllib.request.Request("http://127.0.0.1:6001/fragments/online_course_notes",
                             headers={"Authorization": "Bearer " + TOKEN})
body = urllib.request.urlopen(req).read().decode("utf-8")
j = json.loads(body)
html = j.get("data", "")
checks = {
    "len": len(html),
    "has_import_block": "function importFiles()" in html,
    "has_mount": "window.importFiles = importFiles" in html,
    "has_var_observer": "var observer = new MutationObserver" in html,
    "has_const_observer_top": "const observer = new MutationObserver(function" in html,
    "has_const_observer_fn": "const observer = new MutationObserver((mutations)" in html,
}
print(json.dumps(checks, indent=1))
