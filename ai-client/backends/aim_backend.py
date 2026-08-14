import os
import subprocess
from .base import AIBackend


class AimBackend(AIBackend):
    def __init__(self, workspace=""):
        self._conversation_started = False
        self.workspace = workspace if workspace and os.path.isdir(workspace) else None

    def _switch_model(self, model: str):
        subprocess.run(
            ["aim", "model", "switch", model],
            capture_output=True, text=True, timeout=30,
            cwd=self.workspace,
        )

    def chat(self, messages: list[dict], model: str, callback=None) -> str:
        self._switch_model(model)

        if not messages:
            return ""

        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                parts.append(f"[系统设定]: {content}")
            elif role == "user":
                parts.append(f"[用户]: {content}")
            elif role == "assistant":
                parts.append(f"[助手]: {content}")
        prompt = "\n".join(parts)

        try:
            cmd = ["aim", "run" if self._conversation_started else "newrun", prompt]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.workspace,
            )
            self._conversation_started = True

            full_response = ""
            for line in proc.stdout:
                full_response += line
                if callback:
                    callback(line)

            proc.wait(timeout=300)
            return full_response
        except subprocess.TimeoutExpired:
            proc.kill()
            error_msg = "错误: AIM 执行超时"
            if callback:
                callback(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"错误: {str(e)}"
            if callback:
                callback(error_msg)
            return error_msg

    def get_models(self) -> list[str]:
        try:
            result = subprocess.run(
                ["aim", "model", "list"],
                capture_output=True, text=True, timeout=30,
                cwd=self.workspace,
            )
            if result.returncode == 0:
                models = [m.strip() for m in result.stdout.strip().splitlines() if m.strip()]
                if models:
                    return models
            return ["opencode/deepseek-v4-flash-free"]
        except Exception:
            return ["opencode/deepseek-v4-flash-free"]

    def get_status(self) -> str:
        try:
            result = subprocess.run(
                ["aim", "model", "list"],
                capture_output=True, text=True, timeout=10,
                cwd=self.workspace,
            )
            if result.returncode == 0:
                return "已连接"
            return f"错误: {result.returncode}"
        except Exception:
            return "未连接"

    def reset_conversation(self):
        self._conversation_started = False

    def upload_file(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            content_str = content.decode("utf-8", errors="replace")
            result = subprocess.run(
                ["aim", "newrun", f"分析这个文件: {file_path}\n\n{content_str[:2000]}"],
                capture_output=True, text=True, timeout=120,
                cwd=self.workspace,
            )
            if result.returncode == 0:
                return f"文件已上传. 分析: {result.stdout.strip()[:500]}"
            return f"分析文件错误: {result.stderr.strip()}"
        except Exception as e:
            return f"上传文件错误: {str(e)}"
