import json
import uuid
from datetime import datetime
from aim.config import CONVERSATIONS_DIR


def new_conversation(agent_name):
    conv_id = str(uuid.uuid4())[:8]
    data = {
        "id": conv_id,
        "agent": agent_name,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "messages": [],
    }
    path = CONVERSATIONS_DIR / f"{conv_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return conv_id


def get_conversation(conv_id):
    path = CONVERSATIONS_DIR / f"{conv_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def list_conversations(agent_name=None):
    files = sorted(CONVERSATIONS_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    convs = []
    for f in files:
        data = json.loads(f.read_text())
        pid = data["id"]
        if agent_name and data.get("agent") != agent_name:
            continue
        convs.append((pid, data["agent"], len(data["messages"]), data.get("updated_at", "")))
    return convs


def add_message(conv_id, role, content):
    conv = get_conversation(conv_id)
    if not conv:
        return None
    conv["messages"].append({"role": role, "content": content, "timestamp": datetime.now().isoformat()})
    conv["updated_at"] = datetime.now().isoformat()
    path = CONVERSATIONS_DIR / f"{conv_id}.json"
    path.write_text(json.dumps(conv, indent=2, ensure_ascii=False))
    return conv
