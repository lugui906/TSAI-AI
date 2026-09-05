import json
from datetime import datetime
from aim.config import AGENTS_DIR


def list_agents():
    files = sorted(AGENTS_DIR.glob("*.json"))
    agents = []
    for f in files:
        data = json.loads(f.read_text())
        agents.append((f.stem, data.get("description", "")))
    return agents


def get_agent(name):
    path = AGENTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_agent(name, data):
    path = AGENTS_DIR / f"{name}.json"
    if path.exists():
        existing = json.loads(path.read_text())
        existing.update(data)
        existing["updated_at"] = datetime.now().isoformat()
        path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    else:
        data["name"] = name
        data["created_at"] = datetime.now().isoformat()
        data["updated_at"] = data["created_at"]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def delete_agent(name):
    path = AGENTS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def build_system_prompt(agent):
    parts = [f"你是 {agent['name']}。"]
    if agent.get("role"):
        parts.append(f"你的职位/身份是：{agent['role']}。")
    if agent.get("personality"):
        parts.append(f"你的性格：{agent['personality']}。")
    if agent.get("background"):
        parts.append(f"背景设定：{agent['background']}。")
    if agent.get("rules"):
        parts.append(f"行为规则：{agent['rules']}。")
    return "\n".join(parts)
