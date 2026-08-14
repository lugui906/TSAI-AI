#!/usr/bin/env python3
"""模型下载与校验脚本。

用法：
    python3 download_models.py --check [--root DIR]      仅校验已存在模型的 sha256
    python3 download_models.py --list                   列出清单
    python3 download_models.py --download NAME [--root DIR]  下载指定模型（url 需在 models.yaml 中配置）

说明：
    models.yaml 中 url 留空的模型需离线放置（如从 TSAI-OS 系统 /usr/chindows 拷贝）。
    --root 默认取环境变量 AIM_MODEL_ROOT，否则取仓库 ai-voice/share/models。
"""
import argparse
import hashlib
import os
import sys
import urllib.request

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(HERE, "models.yaml")
DEFAULT_ROOT = os.path.join(HERE, "..", "ai-voice", "share", "models")


def load_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return yaml.safe_load(f)["models"]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_dir(root, m):
    return os.path.join(root, m.get("dir", m["name"]))


def check_model(root, m):
    d = model_dir(root, m)
    if not os.path.isdir(d):
        return False, f"目录缺失: {d}"
    for fn in m["files"]:
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            return False, f"文件缺失: {p}"
        if m.get("sha256"):
            got = sha256_of(p)
            if got != m["sha256"]:
                return False, f"sha256 不匹配 {p}: {got}"
    return True, "OK"


def download_model(root, m):
    if not m.get("url"):
        print(f"[跳过] {m['name']}: 未配置 url，请离线放置到 {model_dir(root, m)}")
        return False
    d = model_dir(root, m)
    os.makedirs(d, exist_ok=True)
    for fn in m["files"]:
        url = m["url"].rstrip("/") + "/" + fn
        dst = os.path.join(d, fn)
        print(f"[下载] {url}")
        urllib.request.urlretrieve(url, dst)
    return check_model(root, m)[0]


def main():
    ap = argparse.ArgumentParser(description="TSAI-AI 模型下载/校验")
    ap.add_argument("action", choices=["check", "list", "download"])
    ap.add_argument("name", nargs="?", help="模型名（download 用）")
    ap.add_argument("--root", default=os.environ.get("AIM_MODEL_ROOT") or DEFAULT_ROOT)
    args = ap.parse_args()

    models = load_manifest()
    if args.action == "list":
        for m in models:
            print(f"{m['name']:20s} {m['desc']}  size={m['size']}")
        return 0

    targets = [m for m in models if args.name in (None, m["name"])]
    failed = 0
    for m in targets:
        if args.action == "download":
            ok = download_model(args.root, m)
        else:
            ok, msg = check_model(args.root, m)
            print(f"{m['name']:20s} {msg}")
        if not ok:
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
