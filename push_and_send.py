#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_and_send.py
----------------
1. 生成今日 HTML 报告
2. 推送到 GitHub（触发 GitHub Pages）
3. 发送钉钉 ActionCard 卡片消息（带内嵌按钮）

用法：
    python push_and_send.py
"""

import os
import re
import sys
import json
import time
import logging
import argparse
import configparser
import subprocess
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser

import requests

# ─────────────────────────────── 配置 ───────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.ini"
REPO_DIR = SCRIPT_DIR.parent / "medical-daily-report"  # GitHub仓库目录
GITHUB_USERNAME = "kuangbazi"
GITHUB_REPO = "medical-daily-report"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("push_send")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    return logger


def load_config(cfg_path: str) -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(cfg_path, encoding="utf-8")

    def get(section, key, fallback=""):
        val = cfg.get(section, key, fallback=fallback).strip()
        return val

    # 解析所有群配置
    groups = []
    for section in cfg.sections():
        if section.startswith("group_"):
            webhook = cfg.get(section, "webhook", fallback="").strip()
            if not webhook or webhook.startswith("YOUR_"):
                continue
            enabled = cfg.get(section, "enabled", fallback="1").strip()
            keyword = cfg.get(section, "keyword", fallback="").strip()
            groups.append({
                "name":    cfg.get(section, "name", fallback=section).strip(),
                "webhook": webhook,
                "keyword": keyword,
                "enabled": enabled == "1",
            })

    if not groups:
        raise ValueError("config.ini 中没有找到已配置的群")

    return {
        "app_key":    get("dingtalk", "app_key"),
        "app_secret": get("dingtalk", "app_secret"),
        "groups":     groups,
        "report_dir": Path(get("settings", "report_dir", str(Path(r"D:\Qclaw\医院信息化与AI动态")))),
    }


def read_template(template_path: Path) -> str:
    return template_path.read_text(encoding="utf-8")


def extract_summary_from_html(html_content: str, filename: str = "") -> tuple[str, str]:
    """从HTML报告中提取标题和摘要，返回(标题, 摘要内容)
    
    标题格式：医院信息化与AI每日简报_2026-04-24
    摘要格式：
        **【行业动态】**
        1. **标题**：摘要（第一句，50字内）
        2. **标题**：摘要（第一句，50字内）
        ...
        **【标杆案例】**
        1. **标题**：摘要（第一句，50字内）
        ...
    """
    
    # 标题：文件名去掉.html后缀
    title = filename.replace(".html", "") if filename else "医院信息化与AI每日简报"
    
    def strip_html(text: str) -> str:
        """去除HTML标签并清理空白"""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def get_first_sentence(text: str, max_len: int = 50) -> str:
        """提取第一句，限制长度"""
        text = text.strip()
        # 找到第一个句号/分号/逗号（中文优先）
        for sep in ['。', '；', '，', '.', ';', ',']:
            if sep in text:
                text = text.split(sep)[0] + sep
                break
        if len(text) > max_len:
            text = text[:max_len] + "..."
        return text
    
    # 通用卡片提取正则：兼容 "card" 和 "card case-block" 等多 class 写法
    card_pattern = r'<div class="card(?: \w+)*">.*?<div class="card-title">.*?<a[^>]*>([^<]+)</a>.*?<div class="card-summary">(.*?)</div>'
    
    lines = []
    
    # ── 行业动态 ──
    dynamics_match = re.search(
        r'<div class="section-header dynamics">.*?<span>行业动态[^<]*</span>.*?<div class="section-body">(.*?)</div>\s*</div>\s*<!-- =====',
        html_content, re.DOTALL
    )
    if dynamics_match:
        cards = re.findall(card_pattern, dynamics_match.group(1), re.DOTALL)
        lines.append("**【行业动态】**")
        for i, (card_title, card_summary) in enumerate(cards[:4], 1):
            card_title = strip_html(card_title)
            card_summary = strip_html(card_summary)
            card_summary = get_first_sentence(card_summary, 40)
            # 标题超长截断
            if len(card_title) > 35:
                card_title = card_title[:35] + "..."
            lines.append(f"{i}. **{card_title}**：{card_summary}")
    
    # ── 标杆案例 ──
    case_match = re.search(
        r'<div class="section-header case">.*?<span>标杆案例[^<]*</span>.*?<div class="section-body">(.*?)</div>\s*</div>',
        html_content, re.DOTALL
    )
    if case_match:
        cards = re.findall(card_pattern, case_match.group(1), re.DOTALL)
        lines.append("")
        lines.append("**【标杆案例】**")
        for i, (card_title, card_summary) in enumerate(cards[:2], 1):
            card_title = strip_html(card_title)
            card_summary = strip_html(card_summary)
            card_summary = get_first_sentence(card_summary, 40)
            if len(card_title) > 35:
                card_title = card_title[:35] + "..."
            lines.append(f"{i}. **{card_title}**：{card_summary}")
    
    if not lines:
        date_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', html_content)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y年%m月%d日")
        return (title, f"{date_str} 报告已更新，请点击查看详情")
    
    return (title, "\n".join(lines))


def build_html_report(cfg: dict, logger: logging.Logger) -> tuple[Path, str, str]:
    """构建今日日报（用日期命名）并生成自动跳转首页，返回(首页路径, 今日标题, 今日摘要)"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_dir = cfg["report_dir"]
    
    # 1. 扫描今日报告
    today_html = None
    for pattern in [f"*简报_{today}.html", f"*日报_{today}.html"]:
        files = list(report_dir.glob(pattern))
        if files:
            today_html = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            break
    
    if not today_html:
        raise FileNotFoundError(f"未找到今日报告：{today}")
    
    # 2. 用日期命名复制到仓库（避免覆盖历史）
    today_file = REPO_DIR / f"{today}.html"
    html_content = today_html.read_text(encoding="utf-8")
    today_file.write_text(html_content, encoding="utf-8")
    logger.info(f"今日报告已保存：{today_file.name}")
    
    # 3. 提取今日报告摘要
    report_title, report_summary = extract_summary_from_html(html_content, today_file.name)
    
    # 4. 生成自动跳转首页
    today_str = datetime.now().strftime("%Y年%m月%d日")
    index_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0;url={today}.html">
  <title>跳转中...</title>
  <style>
    body {{ font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
    .container {{ text-align: center; }}
    h1 {{ color: #1a3a6b; margin-bottom: 20px; }}
    p {{ color: #666; }}
    a {{ color: #1565C0; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>🏥 医院信息化与AI动态日报</h1>
    <p>{today_str} 报告加载中...</p>
    <p>如果未自动跳转，请 <a href="{today}.html">点击这里</a></p>
  </div>
  <script>window.location.href = "{today}.html";</script>
</body>
</html>"""
    
    index_file = REPO_DIR / "index.html"
    index_file.write_text(index_html, encoding="utf-8")
    logger.info(f"首页已生成，自动跳转到 {today}.html")
    
    return index_file, report_title, report_summary


def push_to_github(logger: logging.Logger) -> str:
    """推送仓库到 GitHub，返回页面 URL"""
    logger.info("正在推送到 GitHub...")

    # Git 配置
    subprocess.run(["git", "config", "--global", "user.email", "bot@kuang.local"],
                   cwd=REPO_DIR, capture_output=True)
    subprocess.run(["git", "config", "--global", "user.name", "Daily Report Bot"],
                   cwd=REPO_DIR, capture_output=True)

    # 添加文件
    subprocess.run(["git", "add", "."], cwd=REPO_DIR, capture_output=True)

    # 提交
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    result = subprocess.run(
        ["git", "commit", "-m", f"Auto update: {today}"],
        cwd=REPO_DIR, capture_output=True, text=True
    )

    if "nothing to commit" in result.stdout:
        logger.info("文件无变化，跳过提交")
    else:
        logger.info(f"提交成功：{result.stdout.strip()}")

    # 推送
    push_result = subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=REPO_DIR, capture_output=True, text=True
    )

    if push_result.returncode != 0:
        raise RuntimeError(f"推送失败：{push_result.stderr}")

    logger.info("推送完成！")
    return f"https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/"


def get_token(app_key: str, app_secret: str, logger: logging.Logger) -> str:
    """获取 access_token"""
    r = requests.get(
        "https://oapi.dingtalk.com/gettoken",
        params={"appkey": app_key, "appsecret": app_secret},
        timeout=10
    )
    data = r.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 token 失败：{data}")
    return data["access_token"]


def send_action_card(webhook: str, title: str, summary: str, url: str, keyword: str, logger: logging.Logger):
    """发送 ActionCard 卡片消息（Markdown正文 + 内嵌按钮）"""
    # 标题需要包含关键词
    full_title = f"[{keyword}] {title}" if keyword else title
    
    payload = {
        "msgtype": "actionCard",
        "actionCard": {
            "title": full_title,
            "text": summary,   # Markdown 格式正文
            "btnOrientation": "0",
            "singleTitle": "查看完整报告",
            "singleURL": url
        }
    }

    r = requests.post(webhook, json=payload, timeout=15)
    data = r.json()
    if data.get("errcode") == 0:
        logger.info("[OK] 发送成功！")
    else:
        raise RuntimeError(str(data))


def main():
    parser = argparse.ArgumentParser(description="生成报告 - 推送GitHub - 发送钉钉卡片")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    logger = setup_logging()

    try:
        cfg = load_config(args.config)

        logger.info("=" * 50)
        logger.info("  报告推送 + 钉钉卡片发送")
        logger.info("=" * 50)

        # Step 1: 构建 HTML
        report_path, report_title, report_summary = build_html_report(cfg, logger)

        # Step 2: 推送到 GitHub
        page_url = push_to_github(logger)
        logger.info(f"页面地址：{page_url}")

        # 等待 GitHub Pages 构建（通常几秒）
        logger.info("等待 GitHub Pages 构建（约 30 秒）...")
        time.sleep(30)

        # Step 3: 获取 token（ActionCard 不需要token，用webhook直发）
        # token = get_token(cfg["app_key"], cfg["app_secret"], logger)

        # Step 4: 发送到各个群
        enabled_groups = [g for g in cfg["groups"] if g["enabled"]]
        logger.info(f"发送到 {len(enabled_groups)} 个群...")

        success = 0

        for group in enabled_groups:
            keyword = group.get("keyword", "").strip()
            logger.info(f"-> 发送到：【{group['name']}】，关键词：'{keyword}'")
            try:
                send_action_card(group["webhook"], report_title, report_summary, page_url, keyword, logger)
                success += 1
            except Exception as e:
                logger.error(f"失败：{e}")

        logger.info(f"\n完成！成功 {success}/{len(enabled_groups)} 个群")
        logger.info(f"报告地址：{page_url}")

    except Exception as e:
        logger.exception(f"错误：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
