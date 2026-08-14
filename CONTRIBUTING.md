# 贡献指南（CONTRIBUTING）

欢迎为 TSAI-AI 贡献代码！本仓库是 TSAI-OS 开源后的 AI 项目集合，工程化基线较低，
你的每一项改进都很宝贵。

## 快速开始

```bash
git clone https://github.com/lugui906/TSAI-AI.git
cd TSAI-AI

# 安装开发工具
pip install ruff pre-commit pytest
pre-commit install          # 提交前自动检查
```

## 提交前检查（本地）

```bash
# 1. Lint（基线：真实 bug E9 + Pyflakes F）
ruff check .

# 2. pre-commit 全量检查
pre-commit run --all-files

# 3. Go 质量（ai-hub）
cd ai-hub && go test ./... && go vet ./...

# 4. Python 测试
cd APS && python -m pytest tests/
cd ai-clock && python -m pytest tests/
```

> 遗留代码暂不强制 `ruff format` 与完整风格规则；**新代码**请遵循完整风格：
> `ruff format . && ruff check --select E,F,I,UP,B,SIM .`

## 代码风格约定

- 新增 `.py` 文件：UTF-8，尽量保持与本仓库现有风格一致。
- 外部命令（`aim` / `opencode` / `tine`）必须通过 `shutil.which` 或 PATH 动态解析，
  禁止硬编码绝对路径（参照各项目已完成的改造）。
- 模型路径支持环境变量覆盖（`AIM_MODEL_ROOT`、`TSAI_MODEL_DIR`），优先相对路径。
- 不得提交密钥、令牌、`.env`；涉及 API Key 一律走 `aim apikey` 加密存储。

## 依赖管理

有依赖清单的 Python 子项目使用 **pip-tools** 锁定版本：

```bash
pip install pip-tools
cd <子项目>
# 编辑 requirements.in 后重新生成锁文件
pip-compile requirements.in -o requirements.txt --strip-extras
```

系统级依赖（PyGObject / PyAudio 等无 wheel 的包）请在 README 中说明 `apt` 安装方式，
不要放入 pip 依赖。

## 提交与 PR

- 提交信息使用简洁描述，例如：`feat: 新增 XXX`、`fix: 修复 XXX`、`docs: 更新 README`。
- 创建 PR 前请通过上方「提交前检查」，CI 会再次验证。
- PR 请填写 `.github/PULL_REQUEST_TEMPLATE.md` 模板。

## 安全问题

发现安全漏洞请**不要**公开提交，直接在 GitHub 提交 Private Security Advisory，
或联系仓库维护者。
