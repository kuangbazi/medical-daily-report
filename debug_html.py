#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

html = Path("2026-04-24.html").read_text(encoding="utf-8")

# 提取标杆案例 section body 内容
case_match = re.search(
    r'<div class="section-header case">.*?<div class="section-body">(.*?)</div>\s*</div>',
    html, re.DOTALL
)
if case_match:
    body = case_match.group(1)
    print("Case body length:", len(body))
    print("First 500 chars (stripped):", body[:500])
    print("\n--- Looking for patterns ---")
    patterns = [
        (r'<div class="card"', "div.card"),
        (r'<h4[^>]*>(.*?)</h4>', "h4"),
        (r'<div class="[^"]*title[^"]*"[^>]*>([^<]+)<', "div class with title"),
        (r'<a[^>]*>([^<]+)</a>', "a tag text"),
    ]
    for pat, name in patterns:
        found = re.findall(pat, body, re.DOTALL)
        print(f"  {name}: {len(found)} matches")
        if found:
            print(f"    first: {repr(found[0][:80])}")
