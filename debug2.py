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

# 提取 case section body
case_match = re.search(
    r'<div class="section-header case">.*?<span>标杆案例[^<]*</span>.*?<div class="section-body">(.*?)</div>\s*</div>',
    html, re.DOTALL
)
if case_match:
    body = case_match.group(1)
    print(f"Case body length: {len(body)}")
    
    card_pattern = r'<div class="card(?: [\w-]+)*">.*?<div class="card-title">.*?<a[^>]*>([^<]+)</a>.*?<div class="card-summary">(.*?)</div>'
    cards = re.findall(card_pattern, body, re.DOTALL)
    print(f"Card pattern matched: {len(cards)}")
    
    cards2 = re.findall(r'<div class="card case-block">(.*?)</div>', body, re.DOTALL)
    print(f"Direct case-block: {len(cards2)}")
else:
    print("Case section not matched")
