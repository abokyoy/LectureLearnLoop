with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("print(f\"未知的LLM提供商: {self.config[\"llm_provider\"]}\")", "print(f\"未知的LLM提供商: {self.config[\"llm_provider\"]}\")")

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("引号问题已修复")
