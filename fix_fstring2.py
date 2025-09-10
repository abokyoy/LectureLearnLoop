with open("app.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# 找到并修复有问题的行
for i, line in enumerate(lines):
    if "准备监听设备:" in line and "[\"name\"]" in line:
        lines[i] = "        device_name = p.get_device_info_by_index(device_index)[\"name\"]\n"
        lines.insert(i+1, "        self.update_status(f\"准备监听设备: {device_name}\")\n")
        break

with open("app.py", "w", encoding="utf-8") as f:
    f.writelines(lines)

print("f-string语法错误已修复")
