# chindows 打包与更新

`/usr/chindows`（TSAI-OS 的全部 AI 应用）的 ZIP / DEB 打包与一键安装。

## 打包 .deb（普通 Ubuntu 系系统可直接安装）

```bash
sudo /usr/chindows/packaging/build_deb.sh
# 输出: packaging/dist/chindows_12.0.0_all.deb
```

安装到目标 Ubuntu 机器：

```bash
sudo apt install ./chindows_12.0.0_all.deb
# 或 sudo dpkg -i chindows_12.0.0_all.deb && sudo apt -f install
```

deb 内容：整棵 `/usr/tsai-12（附 /usr/chwindows、/usr/chwindows 兼容链接）` 应用树、16 个应用菜单项、`/usr/bin` 入口
（clockai / opencode / se-model-manager / tsai-airgestured）+ Go 预编译的 `aim`
（AIM 2.0 中间件）、systemd 用户服务
（chinai3-app、tsai-airgestured）、`/etc/tsai-airgestured.conf` 配置。
`postinst` 会：清理缓存、刷新菜单与图标、尽力用 pip 安装运行时 Python 依赖。

### 预制服务（非 apt、随包分发）

- **aim（Go，AIM 2.0 中间件）**：构建时用 `go build -ldflags=-s -w` 预编译，安装为
  `/usr/bin/aim`（merged-usr 下即 `/bin/aim`）。`run`/`newrun`/`serve`/`change` 等
  命令委托给 `opencode`。
- **opencode（双架构二进制）**：随包带 `opencode-linux-x64` + `opencode-linux-arm64`
  （位于 `/usr/lib/tsai-12/opencode/`）；`/usr/bin/opencode` 包装脚本按目标机
  架构选择对应二进制，目标机无需安装 node/npm。

### 运行前提与未随包附带的大件

- **Python 依赖**：`Depends` 覆盖了 apt 仓库可得的包（flask/GObject/gi/cairo/
  numpy/opencv/tk/psutil 等）；pip-only 的 `edge-tts faster-whisper pywhispercpp
  rapidocr webrtcvad schedule` 由 `postinst` 自动安装（需联网，失败提示手动执行）。
- **模型（不在包内，需按需放置）**：
  - 语音助手 `aai`：`/usr/chindows/aai/share/models` 放 faster-whisper 模型（`model.bin`）。
  - 隔空手势 `gh`：`/usr/share/tsai-airgestured/models` 放 `palm.tflite`，并保证摄像头可用。
- **ChinAI3 需要在 Gtk4 + WebKitGTK 6.0**（Ubuntu 25.04+ / 较新发行版）；
  更旧 Ubuntu 上主界面会报缺 `gi.require_version("WebKit","6.0")`，其余应用仍可正常使用。

## 打包（生成 ZIP）

```bash
sudo /usr/chindows/packaging/build_zip.sh          # 全量 ~1.2G（含 aai 模型等）
sudo /usr/chindows/packaging/build_zip.sh --lite   # 精简版，剔除模型/squashfs 等大体积产物
```

产物输出到 `/usr/chindows/packaging/dist/chindows-<时间戳>.zip`。

自动排除：`__pycache__` / `*.pyc` / `*.egg-info` / `data/workdir` / 日志 / 旧 zip。

## 安装 / 更新（含应用菜单自动修复）

```bash
sudo /usr/chindows/packaging/install.sh [chindows-*.zip]
# 不带参数时自动选用 dist/ 里最新的 zip
```

install.sh 会依次执行：

1. `unzip -o` 解包覆盖 `/usr/chindows`（保留额外的旧文件）
2. 修正属主为 `root:root` 与入口脚本可执行位
3. 清理 `__pycache__` / `*.pyc`
4. **应用菜单自动安装**：把 `packaging/desktop/*.desktop`（16 项）复制到
   `/usr/share/applications`，并删除旧命名残留（ai-knowledge 等旧文件名）
5. 刷新菜单数据库与图标缓存（`update-desktop-database` / `gtk-update-icon-cache`）
6. 提示重启 ChinAI3 常驻服务

## 菜单修复说明

- 已修复 `com.tsai.ai-knowledge` / `com.tsai.ai-screen-control` 中 Categories 的
  未注册值（`KnowledgeManagement` / `RemoteControl`）
- 已删除损坏的 `/usr/share/applications/display-im7.q16.desktop`（单行垃圾文本，
  曾导致 `update-desktop-database` 整体失败、应用菜单不刷新）

## 应用桌面项清单（packaging/desktop/）

ai-voice(aai) · chindows-update(update) · com.aipc.manager(mgr) ·
com.local.AiAssistant(key) · com.tsai.ai-agent(bai) · com.tsai.ai-knowledge(z) ·
com.tsai.ai-note(ainote2) · com.tsai.ai-screen-control(scr) ·
com.tsai.ai-timer(clockai) · com.tsai.chinai3(chinai3) ·
com.tsai.meeting-hm(hm) · com.tsai.meeting-hy(hy) · gh(隔空手势) ·
se-model-manager(se) · token-monitor(l) · webai(wai)
