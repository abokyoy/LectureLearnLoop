# 找 online_course_notes.html 中 L10700-11150 间 script 块边界 + handlePractice 相关行
p = r"e:\LLM\LectureLearnLoop\server\templates\pages\online_course_notes.html"
lines = open(p, encoding="utf-8").read().splitlines()
out = []
for i in range(10650, min(11160, len(lines))):
    t = lines[i].strip()
    if "<script" in t or "</script" in t:
        out.append(f"{i+1}: {t[:90]}")
print("\n".join(out))
print("---")
for i in range(len(lines)):
    t = lines[i]
    if "window.handlePractice" in t or "function handlePractice" in t:
        print(f"{i+1}: {t.strip()[:100]}")
