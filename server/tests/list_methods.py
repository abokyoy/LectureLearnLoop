import ast
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = r"e:\LLM\LectureLearnLoop\server\knowledge_management.py"
tree = ast.parse(open(path, encoding="utf-8").read())
targets = {"SubjectManager", "KnowledgePointManager", "ErrorQuestionManager",
           "KnowledgeManagementSystem", "MindmapManager", "PracticeRecordManager"}
for c in tree.body:
    if isinstance(c, ast.ClassDef) and c.name in targets:
        print(f"\n=== class {c.name} ===")
        for n in c.body:
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
                args = [a.arg for a in n.args.args]
                print(f"  {n.lineno:>5} def {n.name}({', '.join(args)})")
