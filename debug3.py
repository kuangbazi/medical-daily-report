#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
import re

today = "2026-04-24"
files = list(Path(r"D:\Qclaw\医院信息化与AI动态").glob(f"*简报_{today}.html"))
if not files:
    files = list(Path(r"D:\Qclaw\医院信息化与AI动态").glob(f"*日报_{today}.html"))

html = files[0].read_text(encoding="utf-8")

# 找标杆案例 section-header 附近的完整内容
idx = html.find('<div class="section-header case">')
if idx >= 0:
    # 截取从 case section-header 到下一个 section-header（或文件结尾）的内容
    end = html.find('<div class="section-header', idx + 1)
    section_content = html[idx:end if end > 0 else len(html)]
    print(f"Case section total length: {len(section_content)}")
    
    # 找所有 case-block
    cards = re.findall(r'<div class="card case-block">(.*?)</div>', section_content, re.DOTALL)
    print(f"Total case-block cards in section: {len(cards)}")
    
    # 检查 section-body 边界
    body_match = re.search(r'<div class="section-body">(.*)', section_content, re.DOTALL)
    if body_match:
        body_len = section_content.find('</div>', body_match.start()) - body_match.start()
        print(f"Section-body content length: {body_len}")
    
    # 打印 case-block 数量
    for i, c in enumerate(cards):
        title_match = re.search(r'<a[^>]*>(.*?)</a>', c, re.DOTALL)
        title = title_match.group(1).strip() if title_match else 'NO TITLE'
        print(f"  Card {i+1}: {title[:60]}")
