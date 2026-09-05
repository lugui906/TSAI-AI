import sys
import readline
from aim.config import ensure_dirs, load_config, save_config
from aim.agent import list_agents, get_agent, save_agent, delete_agent, build_system_prompt
from aim.conversation import new_conversation, get_conversation, list_conversations, add_message
from aim.llm import chat


def cmd_agent(args):
    if not args:
        print("用法: aim agent <subcommand> [options]")
        print("子命令:")
        print("  list                 列出所有智能体")
        print("  create <name>        创建新智能体")
        print("  show <name>          查看智能体详情")
        print("  delete <name>        删除智能体")
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        agents = list_agents()
        if not agents:
            print("暂无智能体。使用 'aim agent create <name>' 创建。")
            return
        print(f"{'名称':<20} {'描述':<40}")
        print("-" * 60)
        for name, desc in agents:
            print(f"{name:<20} {desc:<40}")

    elif sub == "create":
        if not rest:
            print("用法: aim agent create <name>")
            return
        name = rest[0]
        if get_agent(name):
            print(f"智能体 '{name}' 已存在，将更新现有条目。")
        data = {}
        print(f"创建智能体: {name}")
        data["description"] = input("简短描述: ").strip()
        data["role"] = input("职位/身份: ").strip()
        data["personality"] = input("性格特点: ").strip()
        data["background"] = input("背景设定: ").strip()
        data["rules"] = input("行为规则: ").strip()
        save_agent(name, data)
        print(f"智能体 '{name}' 已保存到 ~/.config/aim/agents/{name}.json")

    elif sub == "show":
        if not rest:
            print("用法: aim agent show <name>")
            return
        name = rest[0]
        agent = get_agent(name)
        if not agent:
            print(f"智能体 '{name}' 不存在。")
            return
        for k, v in agent.items():
            print(f"{k}: {v}")

    elif sub == "delete":
        if not rest:
            print("用法: aim agent delete <name>")
            return
        name = rest[0]
        if delete_agent(name):
            print(f"智能体 '{name}' 已删除。")
        else:
            print(f"智能体 '{name}' 不存在。")

    else:
        print(f"未知子命令: {sub}")


def cmd_newrun(args):
    if not args:
        print("用法: aim newrun <agent_name>")
        print("可用的智能体:")
        agents = list_agents()
        if not agents:
            print("  (无，请先运行 'aim agent create <name>')")
            return
        for name, desc in agents:
            print(f"  {name}: {desc}")
        return

    agent_name = args[0]
    agent = get_agent(agent_name)
    if not agent:
        print(f"智能体 '{agent_name}' 不存在。")
        print("可用智能体:")
        for name, desc in list_agents():
            print(f"  {name}: {desc}")
        return

    conv_id = new_conversation(agent_name)
    print(f"=== 与 {agent_name} 的新对话 (ID: {conv_id}) ===")
    print("输入 'exit' 退出，输入 '/save' 保存并退出。\n")

    system_prompt = build_system_prompt(agent)
    messages = [{"role": "system", "content": system_prompt}]

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break
        if user_input == "/save":
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        add_message(conv_id, "user", user_input)
        print(f"{agent_name}: ", end="", flush=True)
        reply = chat(messages)
        if reply:
            messages.append({"role": "assistant", "content": reply})
            add_message(conv_id, "assistant", reply)

    print(f"\n对话已保存 (ID: {conv_id})。使用 'aim run {conv_id}' 继续对话。")


def cmd_run(args):
    conv_id = args[0] if args else None

    if not conv_id:
        convs = list_conversations()
        if not convs:
            print("没有找到对话记录。")
            return
        conv_id = convs[0][0]
        print(f"使用最近的对话 (ID: {conv_id})")
        for pid, agent_name, msg_count, updated in convs[:5]:
            print(f"  {pid}: {agent_name} ({msg_count} 条消息)")

    conv = get_conversation(conv_id)
    if not conv:
        print(f"对话 '{conv_id}' 不存在。")
        return

    agent_name = conv["agent"]
    agent = get_agent(agent_name)
    if not agent:
        print(f"智能体 '{agent_name}' 不存在。")
        return

    system_prompt = build_system_prompt(agent)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conv["messages"]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    print(f"=== 继续与 {agent_name} 的对话 (ID: {conv_id}) ===")
    print(f"已有 {len(conv['messages'])} 条消息。输入 'exit' 退出，输入 '/save' 保存并退出。\n")

    for msg in conv["messages"]:
        role_label = "你" if msg["role"] == "user" else agent_name
        print(f"{role_label}: {msg['content']}")

    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("exit", "quit"):
            break
        if user_input == "/save":
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        add_message(conv_id, "user", user_input)
        print(f"{agent_name}: ", end="", flush=True)
        reply = chat(messages)
        if reply:
            messages.append({"role": "assistant", "content": reply})
            add_message(conv_id, "assistant", reply)

    print(f"\n对话已保存 (ID: {conv_id})。")


def cmd_config(args):
    cfg = load_config()
    if not args:
        print("当前配置:")
        for k, v in cfg.items():
            masked = v[:6] + "..." if k == "api_key" and len(v) > 6 else v
            print(f"  {k}: {masked}")
        print("\n环境变量:")
        print("  AIM_API_KEY   - API 密钥")
        print("  AIM_API_BASE  - API 地址 (默认: https://api.openai.com/v1)")
        print("  AIM_MODEL     - 模型名称 (默认: gpt-3.5-turbo)")
        return

    key = args[0]
    if len(args) < 2:
        print(f"{key}: {cfg.get(key, '未设置')}")
        return

    value = " ".join(args[1:])
    cfg[key] = value
    save_config(cfg)
    print(f"已设置 {key} = {value}")


def cmd_list(_args):
    convs = list_conversations()
    if not convs:
        print("暂无对话。使用 'aim newrun <agent_name>' 开始新对话。")
        return
    print(f"{'ID':<12} {'智能体':<20} {'消息数':<8} {'最后更新':<30}")
    print("-" * 70)
    for pid, agent_name, msg_count, updated in convs[:20]:
        print(f"{pid:<12} {agent_name:<20} {msg_count:<8} {updated:<30}")


def main():
    ensure_dirs()
    if len(sys.argv) < 2:
        print("用法: aim <command> [options]")
        print("命令:")
        print("  newrun <agent>    开始与新智能体的对话")
        print("  run [conv_id]     继续对话")
        print("  agent <sub>       管理智能体")
        print("  list              列出所有对话")
        print("  config [key] [val] 查看/设置配置")
        print("  gui               启动图形界面")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "gui":
        from aim.gui import main as gui_main
        gui_main()
        return

    commands = {
        "newrun": cmd_newrun,
        "run": cmd_run,
        "agent": cmd_agent,
        "list": cmd_list,
        "config": cmd_config,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: newrun, run, agent, list, config, gui")
