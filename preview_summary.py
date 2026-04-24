#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""预览完整 Markdown"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import re
from pathlib import Path
from datetime import datetime

def strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_first_sentence(text: str, max_len: int = 999) -> str:
    text = text.strip()
    for sep in ['。', '；', '，', '.', ';', ',']:
        if sep in text:
            text = text.split(sep)[0] + sep
            break
    if len(text) > max_len:
        text = text[:max_len] + "..."
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

def get_section_html(section_class):
    idx = next((i for i, (_, h) in enumerate(header_positions) if section_class in h), None)
    if idx is None:
        return ""
    start = header_positions[idx][0]
    end = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(html)
    return html[start:end]

lines = [f"**{title}**", ""]

dynamics_html = get_section_html("dynamics")
if dynamics_html:
    cards = re.findall(card_pattern, dynamics_html, re.DOTALL)
    print(f"[DEBUG] 行业动态共 {len(cards)} 条")
    lines.append("**【行业动态】**")
    for i, (card_title, card_summary) in enumerate(cards, 1):
        card_title = strip_html(card_title)
        card_summary = strip_html(card_summary)
        card_summary = get_first_sentence(card_summary, 999)
        if len(card_title) > 35:
            card_title = card_title[:35] + "..."
        lines.append(f"{i}. **{card_title}**：{card_summary}")

case_html = get_section_html("case")
if case_html:
    cards = re.findall(card_pattern, case_html, re.DOTALL)
    print(f"[DEBUG] 标杆案例共 {len(cards)} 条")
    lines.append("")
    lines.append("**【标杆案例】**")
    for i, (card_title, card_summary) in enumerate(cards, 1):
        card_title = strip_html(card_title)
        card_title = re.sub(r'^【标杆案例】', '', card_title).strip()
        card_summary = strip_html(card_summary)
        card_summary = get_first_sentence(card_summary, 999)
        if len(card_title) > 35:
            card_title = card_title[:35] + "..."
        lines.append(f"{i}. **{card_title}**：{card_summary}")

print("\n" + "="*60)
print("\n".join(lines))
print("="*60)
