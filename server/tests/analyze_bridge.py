"""提取 CorgiWebBridge 全部槽方法签名（兼容层 1:1 还原依据）。"""
import ast
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = pathlib.Path(r"e:\LLM\LectureLearnLoop_new\overlay_drag_corgi_app.py").read_text(encoding="utf-8", errors="replace")
tree = ast.parse(src)
for c in tree.body:
    if isinstance(c, ast.ClassDef) and c.name == "CorgiWebBridge":
        count = 0
        for n in c.body:
            if isinstance(n, ast.FunctionDef):
                args = [a.arg for a in n.args.args][1:]
                is_slot = any(getattr(d, "id", getattr(d, "attr", "")) == "pyqtSlot" for d in n.decorator_list)
                print(f"{n.lineno:>6} {'[Slot]' if is_slot else '      '} def {n.name}({', '.join(args)})")
                count += 1
        print("total:", count)
