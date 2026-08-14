#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 引擎：分页文本提取。"""
import os


class PdfEngine:
    def __init__(self, path: str = None):
        self.path = path
        self.pages = []          # [str]
        self.dirty = False
        if path:
            self._load(path)

    def _load(self, path: str):
        from pypdf import PdfReader
        reader = PdfReader(path)
        self.pages = []
        for page in reader.pages:
            self.pages.append((page.extract_text() or "").strip())
        self.dirty = False

    def save(self, path: str):
        # PDF 编辑以文本重排输出；中文字体自动探测注册
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfgen import canvas

        font_name = "Helvetica"
        # 方案1：Adobe CID 内置中文字体（无需字体文件）
        try:
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
            font_name = "STSong-Light"
        except Exception:
            # 方案2：本地 TTF/TTC 字体
            from reportlab.pdfbase.ttfonts import TTFont
            cjk_candidates = [
                "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/arphic/uming.ttc",
            ]
            for cand in cjk_candidates:
                if os.path.exists(cand):
                    try:
                        if cand.endswith(".ttc"):
                            pdfmetrics.registerFont(TTFont("APSCJK", cand, subfontIndex=0))
                        else:
                            pdfmetrics.registerFont(TTFont("APSCJK", cand))
                        font_name = "APSCJK"
                        break
                    except Exception:
                        continue

        c = canvas.Canvas(path, pagesize=A4)
        c.setFont(font_name, 12)
        y = A4[1] - 60
        for page in self.pages:
            for line in page.splitlines():
                if y < 50:
                    c.showPage()
                    c.setFont(font_name, 12)
                    y = A4[1] - 60
                c.drawString(50, y, line[:110])
                y -= 14
            c.showPage()
            c.setFont(font_name, 12)
            y = A4[1] - 60
        c.save()
        self.path = path
        self.dirty = False

    def to_text(self) -> str:
        out = [f"# PDF：{os.path.basename(self.path) if self.path else '新建'}（{len(self.pages)} 页）"]
        for i, p in enumerate(self.pages, 1):
            if p:
                out.append(f"\n## 第 {i} 页\n{p}")
        return "\n".join(out)
