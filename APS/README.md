# APS — AI 原生办公套件（对标 WPS）

> **A**I **P**ower **S**uite：WPS 的功能 + AIM 核心接入，
> AI 几乎可以对任何文档做任何操作。

## 定位

WPS/Office 是"人操作文档"的工具；APS 是"AI 操作文档"的工具。

- 文档引擎：python-pptx / openpyxl / python-docx / reportlab / pypdf
- AI 核心：AIM 中间件（`aim run` / `aim newrun`，完整系统权限）
- 范式：**AI 作为开发工程师** —— AI 直接编写 Python 脚本操作文档，系统自动执行落地
- 界面：GTK4 纯原生（WPS 风格：Ribbon 工具条 + 视图切换 + 右侧 AI 助手）

## 已实现

### 三件套 + PDF
| 模块 | 引擎 | 功能 |
|---|---|---|
| 文字 | python-docx | 富文本编辑（加粗/斜体/字号/颜色/对齐）、标题/正文样式、查找替换、docx/txt 读写 |
| 表格 | openpyxl | 网格单元格编辑、公式栏、插入/删除行列、求和/平均、多工作表、xlsx 读写 |
| 演示 | python-pptx | 缩略图导航、标题/正文编辑、增删/排序幻灯片、版式切换、全屏播放、pptx 读写 |
| PDF | pypdf + reportlab | 分页阅读、文本提取、中文重排输出（STSong CID 字体） |

### AI 中枢（AIM 接入）
- 快捷命令：生成 PPT / Word / Excel、总结、改写、分析、问答、翻译
- 文档上下文自动注入（路径 + 类型 + 内容摘录）
- AI 编写 python-pptx/openpyxl/python-docx 脚本 → 自动执行 → 文档落地
- 实测：AI 一键生成 3 页 PPT ✅

## 技术栈

- Python 3.14 + GTK4（PyGObject）
- AIM 2.0 CLI（opencode 引擎）
- python-pptx 1.0.2 / openpyxl 3.1.5 / python-docx / reportlab 5.0 / pypdf 6.15

## 结构

```
APS/
├── main.py                  # 入口（--lo 打开 LibreOffice 伴侣窗口）
├── requirements.txt
├── bin/lo-aps               # 启动器：LibreOffice（带 UNO socket）+ 伴侣窗口
├── aps/
│   ├── core/                # 统一文档模型 + 四类引擎
│   │   ├── docmodel.py
│   │   ├── writer.py / sheet.py / slides.py / pdfview.py
│   ├── ai/
│   │   ├── aim.py           # 共享 AimBridge（AIM CLI 子进程，单一实现）
│   │   └── agent.py         # 提示词体系 + 快捷命令
│   ├── lo/                  # LibreOffice 伴侣（外部 GTK 小窗口）
│   │   ├── bridge.py        # UNO socket 桥（端口 2002）
│   │   ├── aps_ai.py        # AI 操作层（提取/提示词/脚本执行）
│   │   ├── aps_doc.py       # UNO 文档操作原语
│   │   └── cli.py           # 命令行版（python -m aps.lo.cli summarize|ask|execute）
│   └── ui/
│       ├── main_window.py   # 桌面套件主窗口
│       ├── lo_companion.py  # LibreOffice 伴侣窗口（外部 GTK 小窗口）
│       └── ribbon.py + writer/sheet/slides/pdf_view.py + ai_panel.py
```

## 运行

桌面套件：
```bash
cd ~/APS && python3 main.py
```

LibreOffice AI 伴侣（外部 GTK 小窗口）：
```bash
bash bin/lo-aps        # 自动启动 LibreOffice（带 UNO socket 端口 2002）+ 伴侣窗口
python3 main.py --lo   # 或仅启动伴侣窗口（LibreOffice 需已带端口 2002 运行）
```

说明：soffice 包装脚本自动注入 `--accept=socket,host=localhost,port=2002`，
伴侣窗口通过该端口对 LibreOffice 当前文档做 AI 总结/问答/自由操作；
AI 输出实时流式刷新，不展示文件内容；LO 重启后自动重连。
多对话：同一会话内第一问用 `aim newrun`，之后自动用 `aim run` 续接上下文，
点「新对话」按钮即重置（下次回到 `aim newrun`）。
精细操作：调整排版 / 文字大小 / 字体 / 颜色 / 对齐 等精细需求时，AI 会自动切换提示词框架——
先告知基本工具（`document` + `aps_doc` 原语），再允许其用 python-pptx / python-docx / openpyxl
直接改文件（`document_path`），改完 `aps_doc.reload(document)` 让 LibreOffice 重新载入。

命令行（无 GUI）：
```bash
python3 -m aps.lo.cli summarize
python3 -m aps.lo.cli ask "文档讲了什么"
python3 -m aps.lo.cli execute "在文档末尾追加一段结论"
```

## 路线图

- [x] 四类文档引擎（打开/编辑/保存）
- [x] GTK4 WPS 风格界面（Ribbon + 三视图 + AI 面板）
- [x] AIM 接入：AI 生成 PPT 实测通过
- [ ] AI 修改现有文档（追加/改样式/填表）
- [ ] 文档问答（AI 读全文后作答）
- [ ] 批量处理（文件夹级 AI 操作）
- [ ] 与 wai 打通：手机远程指挥 APS
- [ ] 公式引擎（SUM/AVERAGE/IF 等）
- [ ] 图表（饼图/柱状图）
- [ ] 富文本完整样式（下划线/高亮/字体家族）

## 彩蛋

AI 是系统本身，而非附加功能。—— 这份 README 描述的正是它的宿命。
