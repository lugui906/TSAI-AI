import json
import httpx
from aim.config import load_config


def chat(messages, stream=True, stream_callback=None, stop_event=None):
    cfg = load_config()
    api_key = cfg["api_key"]
    api_base = cfg["api_base"].rstrip("/")
    model = cfg["model"]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }

    with httpx.Client(timeout=120) as client:
        response = client.post(f"{api_base}/chat/completions", headers=headers, json=body)

    if response.status_code != 200:
        error_msg = f"API error: {response.status_code}\n{response.text}"
        if stream_callback:
            stream_callback(error_msg)
        else:
            print(error_msg)
        return None

    if stream:
        content = ""
        for line in response.iter_lines():
            if stop_event is not None and stop_event.is_set():
                break
            if line:
                line = line.decode() if isinstance(line, bytes) else line
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            content += token
                            if stream_callback:
                                stream_callback(token)
                            else:
                                print(token, end="", flush=True)
                    except json.JSONDecodeError:
                        continue
        if not stream_callback:
            print()
        return content
    else:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if stream_callback:
            stream_callback(content)
        else:
            print(content)
        return content
