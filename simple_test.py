#!/usr/bin/env python3
import requests
import json

def simple_ollama_test():
    url = "http://localhost:11434/api/generate"
    model = "deepseek-r1:14b"
    prompt = "你好"
    
    print(f"测试Ollama连接...")
    print(f"URL: {url}")
    print(f"模型: {model}")
    
    try:
        response = requests.post(url, json={
            "model": model,
            "prompt": prompt,
            "stream": False
        }, timeout=30)
        
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"成功! 回复: {data.get('response', '')}")
            return True
        else:
            print(f"失败: {response.text}")
            return False
            
    except Exception as e:
        print(f"异常: {e}")
        return False

if __name__ == "__main__":
    simple_ollama_test()
