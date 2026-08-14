# model-manager — 模型管理器

GTK3 配置工具，统一管理 `~/.config/opencode/opencode.jsonc`（**opencode 与 aim 共用**的配置文件）。
三个页签：设置默认/小模型、增删改自定义 Provider、切换 AIM 引擎并管理 Provider API Key。

## 架构

```
jsonc.py          自研 JSONC 解析器 + "外科手术式"编辑器（纯标准库）
│                 保留注释与格式的前提下精确替换：set_value / delete_key
└── 关键能力      沿 path（字符串键/数组索引）定位值区间替换；缺键自动创建；
                  删除后清理悬空逗号/空行
model_manager.py  GTK3 GUI + 外部命令封装
├── 配置读写       ensure_config / read_config / 原子写（临时文件 + os.replace）
├── 外部命令       list_models(opencode models)
│                  aim_current_engine / aim_switch_engine（aim oc status/default/openclaw）
│                  aim_list_apikeys / aim_set_apikey / aim_remove_apikey
└── MainWindow     3 页签 Notebook：
                    · 默认模型页（ComboBoxText 可输入，设为主/小模型）
                    · AIM 引擎页（opencode/openclaw 切换 + Provider API Key 表格）
                    · 自定义 Provider 页（ID/名称/BaseURL/模型列表）
```

## 核心运行流程

```
python3 model_manager.py → MainWindow → _load_all()
  → 填充 opencode models + 读取 jsonc 当前 model/small_model/provider
  → 用户操作 → jsonc.set_value/delete_key → 原子写 opencode.jsonc
  → 引擎/Key 操作 → subprocess 调 aim oc / aim apikey
```

## 运行

```bash
python3 model_manager.py        # 在项目目录下运行（jsonc 为同目录模块）
```

需在项目目录下运行，或已将项目目录加入 sys.path。

## 依赖

- `python3-gi` + `gir1.2-gtk-3.0`（GTK3）
- 外部命令：`opencode`、`aim`（含 `aim oc` / `aim apikey` 子命令）、`openclaw`（可选）、一个终端模拟器（可选）

## 配置目标

写入 `~/.config/opencode/opencode.jsonc` 的三个段：

- `model` / `small_model`：默认与大模型
- `provider.<id>`：自定义 Provider（npm 包 + baseURL + apiKey + models）
