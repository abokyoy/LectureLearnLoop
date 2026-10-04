# 批7 验证：登录页/悬浮窗/笔记选择窗/截屏窗 设计系统统一 + 既有验收标记不回归
# 标记约束来源：p4_check.py（音源两项）、r9_acceptance.py（记住登录/确认密码/overlayClose）
import requests

BASE = "http://127.0.0.1:6001"
TOKEN = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
OUT = r"e:\LLM\LectureLearnLoop\server\logs\ui_b7_verify.txt"
H = {"Authorization": "Bearer " + TOKEN}

lines = []


def get(path):
    r = requests.get(BASE + path, headers=H, timeout=15)
    return r.status_code, r.text


# 1. 登录页：橙主题 + sprite 狗 logo + 记住登录/确认密码文案保留 + 无紫色残留
st, login = get("/login")
lines.append(f"login: st={st}")
lines.append(f"login_theme: orange={'#F97316' in login} no_purple={'#6a8dff' not in login and '#4c6ef5' not in login} dog_sprite={'li-dog' in login}")
lines.append(f"login_features: remember={'记住登录' in login} confirm_pw={'确认密码' in login} auto_hint={'自动登录' in login}")

# 2. 悬浮窗：暗窗保留 + 橙色 accent + p4/r9 标记不回归（预计算变量，避开 f-string 表达式内反斜杠坑 P023）
st, ovl = get("/overlay")
has_loopback = 'value="loopback"' in ovl
has_mic = 'value="mic"' in ovl
no_file_src = 'value="file"' not in ovl and "选择音频" not in ovl
lines.append(f"overlay: st={st}")
lines.append(f"overlay_theme: orange_accent={'#F97316' in ovl} no_blue={'#4c8dff' not in ovl} no_camera_emoji={'📷' not in ovl} camera_sprite={'li-camera' in ovl}")
lines.append(f"overlay_markers: loopback={has_loopback} mic={has_mic} no_file_src={no_file_src} overlay_close={'overlayClose' in ovl}")

# 3. 笔记选择窗：路由 /note-picker 200（旧记录 404 系脚本笔误）+ 橙 accent
st, npk = get("/note-picker")
lines.append(f"note_picker: st={st} orange={'#F97316' in npk} no_blue={'#4c8dff' not in npk} no_emoji={'📝' not in npk} file_sprite={'li-file-text' in npk}")

# 4. 截屏窗：橙色框选样式
st, cap = get("/capture")
lines.append(f"capture: st={st} orange_sel={'#F97316' in cap} no_blue={'#4c8dff' not in cap}")

open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("done")
