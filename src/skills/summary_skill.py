import json
from pathlib import Path
from models.deepseek_client import chat

BASE_DIR = Path(__file__).parent.parent.parent

def summarize(content: str) -> dict:
    prompt_path = BASE_DIR / "prompts" / "summary_prompt.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()
    
    response = chat(system_prompt, content)
    
    # ✅ 添加调试日志
    print(f"[DEBUG] DeepSeek 原始返回:\n{response}\n")
    
    try:
        response = response.strip().strip("```json").strip("```").strip()
        result = json.loads(response)
        
        # ✅ 验证必需字段
        required_fields = ["date", "title", "summary", "tags", "category"]
        for field in required_fields:
            if field not in result:
                result[field] = ""
        
        return result
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 解析失败: {e}")
        return {
            "date": "",
            "title": "解析失败",
            "summary": response[:200],
            "tags": ["没看懂的"],
            "category": "没看懂的"
        }