with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# 修复字符串换行问题
content = content.replace("print(f\"未知的LLM提供商: {self.config[\nllm_provider]}\")", "print(f\"未知的LLM提供商: {self.config[\"llm_provider\"]}\")")

# 写入修复后的文件
with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("语法错误已修复")
