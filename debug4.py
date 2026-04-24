#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")

from pathlib import Path
import re

today = "2026-04-24"
files = list(Path(r"D:\Qclaw\医院信息化与AI动态").glob(f"*简报_{today}.html"))
html = files[0].read_text(encoding="utf-8")

# 找所有 section-header 的位置
headers = [(m.start(), m.group()) for m in re.finditer(r'<div class="section-header \w+">', html)]
print("Section headers found:")
for pos, h in headers:
    print(f"  {pos}: {h}")

# 提取 case section（从 case header 到下一个 header）
case_pos = next((p for p, h in headers if 'case' in h), None)
if case_pos:
    next_pos = next((p for p, h in headers if p > case_pos), len(html))
    section_html = html[case_pos:next_pos]
    print(f"\nCase section length: {len(section_html)}")
    
    # 找所有 card
    cards = re.findall(r'<div class="card(?: [\w-]+)*">(.*?)</div>', section_html, re.DOTALL)
    print(f"Cards found: {len(cards)}")
    for i, c in enumerate(cards):
        title = re.search(r'<a[^>]*>(.*?)</a>', c, re.DOTALL)
        print(f"  {i+1}. {title.group(1).strip()[:60] if title else 'NO TITLE'}")
