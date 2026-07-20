from openai import OpenAI
from dotenv import load_dotenv
import os
from pathlib import Path

# 获取当前文件所在目录的上级目录的上级目录（即 knowledge-agent 根目录）
base_dir = Path(__file__).parent.parent.parent
env_path = base_dir / "config" / ".env"
load_dotenv(env_path)

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

def chat(system_prompt, user_content, temperature=0, max_tokens=None):
    kwargs = {"temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        **kwargs
    )
    return response.choices[0].message.content