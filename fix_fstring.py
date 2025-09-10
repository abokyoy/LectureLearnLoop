with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# 修复f-string中的反斜杠问题
content = content.replace("self.update_status(f\"准备监听设备: {p.get_device_info_by_index(device_index)[\"name\"]}\")", "self.update_status(f\"准备监听设备: {p.get_device_info_by_index(device_index)[\"name\"]}\")")

# 写入修复后的文件
with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

print("f-string语法错误已修复")
