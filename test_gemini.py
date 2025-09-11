import os
import sys
import time
import json
import argparse
import requests

def call_gemini_once(api_key, model, prompt, timeout=20):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    headers = {
        "Content-Type": "application/json"
    }

    start = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        elapsed = time.time() - start
        info = {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "elapsed_sec": round(elapsed, 3),
            "url": url,
        }
        try:
            data = resp.json()
        except Exception:
            data = {"raw_text": resp.text[:2000]}

        return info, data, None
    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start
        info = {
            "ok": False,
            "status_code": None,
            "elapsed_sec": round(elapsed, 3),
            "url": url,
        }
        return info, None, e

def call_gemini_with_retries(api_key, model, prompt, retries=3, base_delay=2.0, timeout=20):
    last_err = None
    for attempt in range(1, retries + 1):
        print(f"\n[Attempt {attempt}/{retries}] Sending request...")
        info, data, err = call_gemini_once(api_key, model, prompt, timeout=timeout)
        print(f"- url: {info['url']}")
        print(f"- elapsed: {info['elapsed_sec']}s")
        print(f"- status_code: {info['status_code']}")
        if err:
            print(f"- error: {repr(err)}")
            last_err = err
        else:
            print("- response_ok:", info["ok"])
            print("- raw_json_preview:")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
            if info["ok"]:
                # 尝试提取文本
                try:
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            content = parts[0]["text"]
                            print("\n[Content]")
                            print(content)
                            return True
                except Exception as parse_err:
                    print(f"- parse_error: {repr(parse_err)}")
                # 即使不满足结构，也认为联通成功
                return True

        if attempt < retries:
            delay = base_delay * (2 ** (attempt - 1))
            print(f"Retrying after {delay}s...")
            time.sleep(delay)

    print("\nAll retries failed.")
    if last_err:
        print("Last error:", repr(last_err))
    return False

def main():
    parser = argparse.ArgumentParser(description="Test direct call to Gemini generateContent API.")
    parser.add_argument("--api_key", default=os.getenv("GEMINI_API_KEY", ""), help="Gemini API key (or set env GEMINI_API_KEY)")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest"), help="Gemini model name")
    parser.add_argument("--prompt", default="你好，请用三句话自我介绍。", help="Prompt text to send")
    parser.add_argument("--retries", type=int, default=3, help="Retry count")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout seconds")
    args = parser.parse_args()

    if not args.api_key:
        print("Error: API key is required. Provide --api_key or set env GEMINI_API_KEY.")
        sys.exit(2)

    print("Env diagnostics:")
    print("- HTTP_PROXY:", os.getenv("HTTP_PROXY"))
    print("- HTTPS_PROXY:", os.getenv("HTTPS_PROXY"))
    print("- NO_PROXY:", os.getenv("NO_PROXY"))
    print("- Model:", args.model)

    ok = call_gemini_with_retries(
        api_key=args.api_key,
        model=args.model,
        prompt=args.prompt,
        retries=args.retries,
        timeout=args.timeout
    )
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
