"""提取页面中 pybridge/window.bridge 调用的上下文，确定参数与回调约定。"""
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TPL = pathlib.Path(r"e:\LLM\LectureLearnLoop\server\templates\pages")
targets = ["online_course_notes.html", "learn_from_materials.html", "practice_materials.html", "settings.html"]
KEYS = ["extractKnowledgePoints", "getFileStructure", "loadMarkdownRaw", "saveMarkdownFile",
        "getSubjects", "createNewNote", "render_markdown", "startRecording", "takeScreenshot",
        "summarizeText", "getConfig", "evaluatePracticeAnswers", "generatePracticeQuestions"]

for name in targets:
    s = (TPL / name).read_text(encoding="utf-8", errors="replace")
    print(f"\n########## {name} ##########")
    for k in KEYS:
        for m in list(re.finditer(r"pybridge\." + k + r"\(|bridge\." + k + r"\(", s))[:2]:
            seg = s[m.start(): m.start() + 260]
            print(f"--- {k}: {seg.splitlines()[0][:200]}")
            # 找到参数部分
            mm = re.match(r"(?:pybridge|bridge)\." + k + r"\((.{0,200})", s[m.start():])
            if mm:
                print("    args:", mm.group(1).replace("\n", " ")[:180])
