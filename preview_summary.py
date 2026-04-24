#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预览最终卡片 MD 内容"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import re
from pathlib import Path
from datetime import datetime

def strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def first_sentence(text: str) -> str:
    text = text.strip()
    for sep in ['。', '；', '，', '.', ';', ',']:
        if sep in text:
            return text.split(sep)[0] + sep
    return text

card_pattern = r'<div class="card(?: [\w-]+)*">.*?<div class="card-title">.*?<a[^>]*>([^<]+)</a>.*?<div class="card-summary">(.*?)</div>'

today = datetime.now().strftime("%Y-%m-%d")
files = list(Path(r"D:\Qclaw\医院信息化与AI动态").glob(f"*简报_{today}.html"))
if not files:
    files = list(Path(r"D:\Qclaw\医院信息化与AI动态").glob(f"*日报_{today}.html"))

html = files[0].read_text(encoding="utf-8")
filename = files[0].name
title = filename.replace(".html", "")

header_positions = [(m.start(), m.group()) for m in re.finditer(r'<div class="section-header \w+">', html)]

def get_section_html(cls):
    idx = next((i for i, (_, h) in enumerate(header_positions) if cls in h), None)
    if idx is None:
        return ""
    start = header_positions[idx][0]
    end = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(html)
    return html[start:end]

md_lines = [f"**{title}**", ""]

dynamics_html = get_section_html("dynamics")
if dynamics_html:
    cards = re.findall(card_pattern, dynamics_html, re.DOTALL)
    print(f"[DEBUG] 行业动态 {len(cards)} 条")
    md_lines.append("**【行业动态】**")
    for i, (card_title, card_summary) in enumerate(cards, 1):
        card_title = strip_html(card_title)
        card_summary = strip_html(card_summary)
        md_lines.append(f"{i}. **{card_title}**：{first_sentence(card_summary)}")

case_html = get_section_html("case")
if case_html:
    cards = re.findall(card_pattern, case_html, re.DOTALL)
    print(f"[DEBUG] 标杆案例 {len(cards)} 条")
    md_lines.append("")
    md_lines.append("**【标杆案例】**")
    for i, (card_title, card_summary) in enumerate(cards, 1):
        card_title = strip_html(card_title)
        card_title = re.sub(r'^【标杆案例】', '', card_title).strip()
        card_summary = strip_html(card_summary)
        md_lines.append(f"{i}. **{card_title}**：{first_sentence(card_summary)}")

md_content = "\n".join(md_lines)
print("\n" + "="*60)
print(md_content)
print("="*60)
print(f"\n字符数: {len(md_content)}")
