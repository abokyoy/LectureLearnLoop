# 为 ui_walk_2026 灌入演示数据：学科 + 知识点（供 UI 走查时界面有内容）
import requests

BASE = "http://127.0.0.1:6001"
tok = open(r"e:\LLM\LectureLearnLoop\server\logs\ui_walk_token.txt", encoding="utf-8").read().strip()
H = {"Authorization": "Bearer " + tok}

subjects = {
    "Python 基础": [
        ("构造函数", "对象初始化时自动执行，与类同名，用于建立对象初始状态"),
        ("继承", "子类复用父类字段与方法，支持单继承与多层扩展"),
        ("多态", "同一接口不同实现，运行时按对象实际类型分派调用"),
        ("装饰器", "高阶函数包装，不修改原函数即可增强行为"),
    ],
    "数据结构": [
        ("栈", "后进先出 LIFO，仅栈顶插入与删除"),
        ("队列", "先进先出 FIFO，广泛用于缓冲与调度"),
        ("二叉树", "每个节点至多两个子节点，支持前中后序遍历"),
        ("哈希表", "键值映射，平均 O(1) 查找，冲突需链地址或开放寻址"),
    ],
}
for sub, pts in subjects.items():
    r = requests.post(BASE + "/api/subjects", json={"subject_name": sub}, headers=H, timeout=20)
    print("subject", sub, r.status_code, r.text[:80])
    for name, desc in pts:
        r = requests.post(BASE + "/api/knowledge/point-new",
                          json={"point": {"name": name, "description": desc}, "subject": sub},
                          headers=H, timeout=60)
        print("  point", name, r.status_code, r.text[:80])
