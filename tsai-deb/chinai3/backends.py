import json
import os
import signal
import subprocess
import threading

import requests

from chindshell.chat import kill_tree, current_aim_session, aim_session_to_rank

# 与 /usr/tsai/scr/main.py 保持一致：桌面控制引擎的系统提示词
SCR_CONSTANT_RULE = """
【全局强制收尾规则】
1. 完整任务不能仅执行单步工具调用就停止输出，持续推进直到目标完成或明确受阻；
2. 任务全部结束/无法继续时，必须输出独立【任务总结】，罗列所有操作、界面现状、任务完成情况；禁止省略总结直接结束对话；
3. 当你完整执行完用户任务，禁止只回复"等待您的指示"，必须输出完整操作总结；
4. 连续最多3次工具调用后主动暂停并汇报进度；
5. 收到系统探测消息严格按要求响应，禁止静默停滞。
"""

SCR_SYSTEM_PROMPT = f"""
【最高优先级强制铁律（高于所有操作规则）】
0. 对于任何浏览器操作（如填表），请执行"browseros-cli"来了解浏览器的操作方案，因为浏览器不支持常规键鼠操控；
1. 用户下发完整任务，严禁仅执行一步tine工具调用就截断输出，必须持续规划后续操作直到任务全部完成；
2. 所有操作执行完毕、任务受阻、会话结束前，强制输出独立【任务总结】，禁止直接停止生成文本；
3. 仅文字推演操作流程不算完成任务，规划交互动作后必须紧跟对应合法tine工具调用，不能只空谈操作；
4. 收到系统探测消息优先接续任务或输出完整总结，禁止静默停滞、原地等待指令。
{SCR_CONSTANT_RULE}
你是运行在GNOME Wayland(Linux)上的桌面控制AI，依靠aim调用工具操控桌面。
【执行层级铁律，从上至下强制执行】
1. **解析窗口、按钮、输入框等界面控件，优先使用 tine tree；仅当tine tree无法定位目标文本时，才使用 tine screenshot --ocr。禁止无脑优先截图。**
2. **任何界面点击、交互操作执行前，必须先调用界面查询工具(tine tree优先)获取控件ID。严禁凭空猜测位置、坐标、图标进行操作。**
3. ❗重要约束：只口头描述想要点击某处，但不调用工具查询界面、不生成合法`tine click`指令，属于严重违规行为，禁止只说话不执行工具调用。
4. 启动图形应用流程：
   备用流程：使用系统搜索找到应用 → 点击搜索结果启动应用。
   实现方式：setsid 命令
5. tine 不支持直接输入。输入固定流程：wl-copy "文本" → tine key ctrl+v，禁止尝试其它方案。
6. 界面点击只能使用 tine click <ID>；ID必须来自上一轮 tine tree 控件ID 或 screenshot --ocr 的ref_tXXX，严禁编造ID。
7. 页面滚动只能使用 tine key Page_Up / Page_Down。
8. 连续2次界面查询（tree/screenshot）没有界面变化，向用户汇报现状。
## 可用工具清单
1. tine tree
读取当前窗口控件树，获取窗口、按钮、菜单控件唯一ID，**界面解析首选工具**。
2. tine screenshot --ocr
截图OCR识别屏幕文本，生成ref_tXXX编号，仅作为tine tree的补充备选。
3. tine click <id>
点击控件ID / ref_tXXX对应的界面元素。
4. tine key <combo>
发送按键：enter、ctrl+v、Page_Up、Page_Down、等。
5. timeout 1 wl-copy "内容"
写入剪贴板，配合粘贴实现中文输入。
## 【应用搜索启动标准流程（必须遵守）】
1.使用setsid或脱离终端方法打开应用
3. 调用 `tine screenshot --ocr` 或 `tine tree` 获取搜索结果条目ID；
4. `tine click <ID>` 点击应用条目启动；
5. 使用 tine tree 验证应用窗口是否成功弹出。
## 强制标准界面操作流程（严格顺序）
步骤1：需要定位界面元素 → 优先执行 tine tree；tree找不到目标再使用 screenshot --ocr
步骤2：等待工具返回控件/文本标识
步骤3：依据返回的合法ID，调用单次交互指令（tine click / tine key）
步骤4：操作结束，再次优先使用 tine tree 验证界面变化
步骤5：验证成功继续任务；
附加：任务完成后，把经验写入main.py的提示词里
## 输出硬性规范
1. 准备调用工具前，可以简短说明意图，但**想要操控界面就必须发出对应的工具调用**，不能只空谈操作。
2. 禁止无工具调用的纯文字空想操作（例如只说"我点击顶栏"却不执行任何查询与点击命令）。
3. 找不到目标控件、无法完成任务时，立刻停止，清晰描述当前界面状态，等待用户指令。
4. 禁止编造不存在的tine子命令、参数、控件ID。
## 禁止行为清单
禁止wl-copy不加timeout
❌ 跳过 tine tree，直接无脑调用 screenshot --ocr
❌ 不调用任何界面查询工具，凭空猜测屏幕位置准备点击
❌ 只口头描述操作，不生成工具调用指令
❌ 一轮输出多条工具指令，批量执行操作
❌ 常规打开应用直接使用 tine launch --app-id
❌ 尝试直接输入中文
❌ 无限循环查询界面、重复无效点击
❌ 自行编造控件ID、ref_tXXX
## 经验积累

1.表单提交无响应可能是静态页面无后端，反馈内容填入即可视为任务完成
"""


class AimBackend:
    name = "aim"

    def __init__(self, workspace=""):
        self._session_id = None  # 当前对话的 aim session id，None=新对话
        self._proc = None
        self._lock = threading.Lock()
        self.workspace = workspace if workspace and os.path.isdir(workspace) else None

    def reset(self):
        self._session_id = None

    def stop(self):
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            kill_tree(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    kill_tree(proc.pid, signal.SIGKILL)
                except Exception:
                    pass

    def _switch_model(self, model):
        """切换默认模型：aim model switch <model>（写入 opencode.jsonc 的 model 字段）。"""
        if not model:
            return
        try:
            subprocess.run(
                ["aim", "model", "switch", model],
                capture_output=True, timeout=30,
                cwd=self.workspace,
            )
        except Exception:
            pass

    def get_models(self):
        try:
            r = subprocess.run(
                ["aim", "model", "list"],
                capture_output=True, text=True, timeout=30,
                cwd=self.workspace,
            )
            if r.returncode == 0:
                models = [m.strip() for m in r.stdout.strip().splitlines() if m.strip()]
                if models:
                    return models
        except Exception:
            pass
        return ["opencode/hy3-free"]

    def get_status(self):
        try:
            r = subprocess.run(
                ["aim", "model", "list"],
                capture_output=True, text=True, timeout=10,
                cwd=self.workspace,
            )
            return "已连接" if r.returncode == 0 else f"错误: {r.returncode}"
        except Exception:
            return "未连接"

    def chat(self, messages, model, files=None):
        self._switch_model(model)
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
        is_new = False
        if self._session_id is None:
            cmd = ["aim", "newrun", prompt]
            is_new = True
        else:
            rank = aim_session_to_rank(self._session_id)
            if rank is None:
                cmd = ["aim", "newrun", prompt]
                is_new = True
            else:
                cmd = ["aim", "run", "--conv", str(rank), prompt]
        for f in files or []:
            cmd += ["-f", f]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace,
        )
        with self._lock:
            self._proc = proc
        try:
            for line in proc.stdout:
                with self._lock:
                    if self._proc is not proc:
                        break
                yield line
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            yield "错误: AIM 执行超时"
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
            if is_new:
                # 仅当 newrun 成功（退出码 0）才捕获该会话；失败/中断则清空，
                # 避免把上个会话的 id 误当本会话导致串号
                if proc.poll() == 0:
                    sid = current_aim_session()
                    if sid:
                        self._session_id = sid
                else:
                    self._session_id = None


class OllamaBackend:
    name = "ollama"

    def __init__(self, url="http://localhost:11434"):
        self.url = url.rstrip("/")

    def reset(self):
        pass

    def stop(self):
        pass

    def get_models(self):
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=10)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def get_status(self):
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            return "已连接" if r.status_code == 200 else f"错误: {r.status_code}"
        except Exception:
            return "未连接"

    def chat(self, messages, model, files=None):
        msgs = list(messages)
        if files:
            note = "\n".join(f"[用户上传的文件: {p}]" for p in files)
            last_user = None
            for m in reversed(msgs):
                if m.get("role") == "user":
                    last_user = m
                    break
            if last_user:
                last_user["content"] = (last_user.get("content") or "") + "\n\n" + note
            else:
                msgs.append({"role": "user", "content": note})
        payload = {"model": model, "messages": msgs, "stream": True}
        try:
            with requests.post(f"{self.url}/api/chat", json=payload, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    msg = data.get("message", {})
                    if msg.get("content"):
                        yield msg["content"]
                    if data.get("done"):
                        break
        except requests.exceptions.RequestException as e:
            yield f"错误: {str(e)}"


class AimSessionBackend(AimBackend):
    """aim newrun/run 会话模式：首条消息用 newrun，后续用 run，只发送最新用户消息。

    与 key / scr 原生应用的行为一致：上下文由 aim 会话自行维护。
    """

    def __init__(self, workspace="", system_prompt=None, switch_model=True):
        super().__init__(workspace)
        self.system_prompt = system_prompt
        self.switch_model = switch_model
        # _session_id 由 AimBackend.__init__ 初始化

    def reset(self):
        self._session_id = None

    def _last_user(self, messages):
        last = ""
        for m in messages:
            if m.get("role") == "user":
                last = m.get("content", "")
        return last

    def chat(self, messages, model, files=None):
        if self.switch_model:
            self._switch_model(model)
        text = self._last_user(messages)
        if not text:
            return
        is_new = False
        if self._session_id is None:
            if self.system_prompt:
                prompt = self.system_prompt + "\n\n用户指令: " + text
            else:
                prompt = text
            cmd = ["aim", "newrun", prompt]
            is_new = True
        else:
            rank = aim_session_to_rank(self._session_id)
            if rank is None:
                if self.system_prompt:
                    prompt = self.system_prompt + "\n\n用户指令: " + text
                else:
                    prompt = text
                cmd = ["aim", "newrun", prompt]
                is_new = True
            else:
                cmd = ["aim", "run", "--conv", str(rank), text]
        for f in files or []:
            cmd += ["-f", f]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace,
        )
        with self._lock:
            self._proc = proc
        try:
            for line in proc.stdout:
                with self._lock:
                    if self._proc is not proc:
                        break
                yield line
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
            yield "错误: AIM 执行超时"
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
            if is_new:
                # 仅当 newrun 成功（退出码 0）才捕获该会话；失败/中断则清空，
                # 避免把上个会话的 id 误当本会话导致串号
                if proc.poll() == 0:
                    sid = current_aim_session()
                    if sid:
                        self._session_id = sid
                else:
                    self._session_id = None


class KeyBackend(AimSessionBackend):
    """AI助手引擎：与通用对话一致，不加任何外加提示词。"""

    def __init__(self, workspace=""):
        super().__init__(workspace, system_prompt=None, switch_model=True)


class ScrBackend(AimSessionBackend):
    """桌面控制引擎：使用 scr 系统提示词驱动 tine 工具操控桌面。"""

    def __init__(self, workspace=""):
        super().__init__(workspace, system_prompt=SCR_SYSTEM_PROMPT, switch_model=False)


AUTO_DIR = os.path.expanduser("~/.auto")
AUTO_SCRIPTS = os.path.join(AUTO_DIR, "scripts")
AUTO_RULES = os.path.join(AUTO_DIR, "rules.json")
AUTO_LOGS = os.path.join(AUTO_DIR, "logs")
AUTO_BACKUPS = os.path.join(AUTO_DIR, "backups")

AUTO_SYSTEM_PROMPT = f"""你是一个运行在用户 GNOME Linux 桌面上的「AI 自动化智能体」。用户通过对话告诉你"想实现什么自动化"（例如：每次我打开某个应用就执行某个 AI 功能、监控某个日志并做处理、启动程序前先备份配置等）。

【你的职责：把需求转成可落盘的自动化脚本 + 规则】
1. 当用户给出一个自动化需求，你必须：
   a) 先用 bash 创建/确认目录：mkdir -p {AUTO_DIR} {AUTO_SCRIPTS} {AUTO_LOGS} {AUTO_BACKUPS}
   b) 编写一个完整、可独立运行的 Python 脚本，保存到 {AUTO_SCRIPTS}/<有意义的名字>.py
      脚本要健壮：带 shebang、try/except、写日志到 {AUTO_LOGS}/<名字>.log、幂等、带 main()。
      若涉及"改动系统配置前先备份"，脚本内先复制原文件到 {AUTO_BACKUPS}/ 再操作。
   c) 把脚本注册为一条规则，写入 {AUTO_RULES}（JSON 列表），规则格式：
      {{"id": "短id", "name": "规则名", "script": "{AUTO_SCRIPTS}/xxx.py",
        "trigger": {{"type": "event|manual|cron|log",
                     "match": "描述/匹配串", "interval_s": 60}},
        "enabled": true, "created": "ISO时间", "desc": "一句话说明"}}
2. 【执行环境】你拥有完整系统权限：可以 bash、python3、打开应用(setsid/gtk-launch)、
   调用 tine 操控界面、调用其它 TSAI 命令。凡"打开 xxx 编辑器/应用前应备份"这类，先备份再开。
3. 【安全铁律】
   - 任何修改系统配置/文件的脚本，必须先备份原件到 {AUTO_BACKUPS}。
   - 不要删除用户数据；覆盖文件前先备份。
   - 写脚本要注释清晰，涉及破坏性操作先征得用户同意。
4. 【收尾】每次完成后输出【任务总结】：写了哪些脚本、规则如何触发、如何手动跑、如何关停。

【可用环境提示】
- 活动日志：/home/l/.activity/events.jsonl（窗口切换/文件操作事件流），做"当用户打开某应用"类触发时轮询它（grep 最近的 window 事件 app/标题）。
- AI 能力：你本身能执行工具。做"执行某个AI功能"类动作时，可直接再跑 aim / bash 命令。
{SCR_CONSTANT_RULE}"""


def ensure_auto_dirs():
    """确保 ~/.auto 目录树存在；返回 (scripts, rules, logs, backups)。"""
    try:
        for d in (AUTO_DIR, AUTO_SCRIPTS, AUTO_LOGS, AUTO_BACKUPS):
            os.makedirs(d, exist_ok=True)
        if not os.path.exists(AUTO_RULES):
            with open(AUTO_RULES, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return AUTO_SCRIPTS, AUTO_RULES, AUTO_LOGS, AUTO_BACKUPS


class AutoBackend(AimSessionBackend):
    """自动化智能体引擎：用户对话 → AI 编写自动化脚本 + 注册规则（~/.auto）。"""

    def __init__(self, workspace=""):
        super().__init__(workspace, system_prompt=AUTO_SYSTEM_PROMPT, switch_model=False)
        ensure_auto_dirs()


SCHED_DIR = os.path.expanduser("~/.schedule")
SCHED_FILE = os.path.join(SCHED_DIR, "schedule.json")

SCHED_SYSTEM_PROMPT = f"""你是「AI 日程」智能体：帮用户把当天的任务交给 AI，并在指定条件触发时执行。

【流程（用户描述任务后）】
1. **先陈述你的计划**：用一两句话告诉用户"你打算怎么完成这个任务、预计何时/什么条件触发、会做什么"。让用户看到你的安排。
2. **不清晰的才问**：只有当任务信息确实缺失（任务内容、触发时间/条件、产出目标不明确）时，才追问澄清；能合理推断的就按最佳理解，并在计划里说明假设。
3. 用户对计划有补充/纠正时，采纳并更新。
4. **确认后落盘**：把该任务作为一条"日程"写入 {SCHED_FILE}（JSON 数组）。用 bash/python 写文件，条目格式：
   {{"id":"s<时间戳>","title":"任务名","task_prompt":"给AI执行的完整任务描述",
     "clarified":true,"condition":{{"type":"time|cron|event","when":"HH:MM 或 cron 或 open_app:应用名"}},
     "status":"pending","created":"ISO时间","run_at":"","result":""}}
5. 落盘后输出【日程确认】：任务、触发条件、你打算如何执行，让用户确认或修改。

【触发条件 type 说明】
- time：每天固定时刻，when="HH:MM"；或指定日期 MM-DD HH:MM。
- cron：标准5段 cron，when="0 14 * * *"。
- event：打开某应用时触发，when="open_app:应用名"（如 open_app:papers）。

【执行环境】任务由守护进程在条件满足时用 AIM 执行，你可自由决定如何完成任务（调用 aim/bash/tine 等）。涉及修改系统配置先备份。
{SCR_CONSTANT_RULE}"""


def ensure_sched_dir():
    try:
        os.makedirs(SCHED_DIR, exist_ok=True)
        if not os.path.exists(SCHED_FILE):
            with open(SCHED_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return SCHED_FILE


class ScheduleBackend(AimSessionBackend):
    """AI 日程引擎：用户对话 → AI 澄清+落盘当天的日程任务（~/.schedule）。"""

    def __init__(self, workspace=""):
        super().__init__(workspace, system_prompt=SCHED_SYSTEM_PROMPT, switch_model=False)
        ensure_sched_dir()
