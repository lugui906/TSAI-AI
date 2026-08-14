import json
import requests
from .base import AIBackend


class OllamaBackend(AIBackend):
    def __init__(self, url: str = "http://localhost:11434"):
        self.url = url.rstrip("/")

    def chat(self, messages: list[dict], model: str, callback=None) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                stream=True,
                timeout=300,
            )
            response.raise_for_status()

            full_response = ""
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            full_response += content
                            if callback:
                                callback(content)
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

            return full_response
        except requests.exceptions.RequestException as e:
            if callback:
                callback(f"Error: {str(e)}")
            return f"Error: {str(e)}"

    def get_models(self) -> list[str]:
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=10)
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except requests.exceptions.RequestException:
            return []

    def get_status(self) -> str:
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            if response.status_code == 200:
                return "Connected"
            return f"Error: {response.status_code}"
        except requests.exceptions.RequestException:
            return "Not connected"

    def upload_file(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                response = requests.post(
                    f"{self.url}/api/chat",
                    json={
                        "model": "llama3",
                        "messages": [
                            {
                                "role": "user",
                                "content": f"请分析这个文件: {file_path}",
                            }
                        ],
                    },
                    files={"file": f},
                    timeout=300,
                )
            response.raise_for_status()
            return "File uploaded for analysis"
        except requests.exceptions.RequestException as e:
            return f"Error uploading file: {str(e)}"