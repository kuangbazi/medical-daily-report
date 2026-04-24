#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
push_and_send.py
----------------
1. 生成今日 HTML 报告
2. 推送到 GitHub（触发 GitHub Pages）
3. 发送钉钉 ActionCard 卡片消息（带链接）

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


def extract_summary_from_html(html_content: str) -> str:
    """从HTML报告中提取摘要，转换为Markdown格式"""
    
    # 提取头部信息
    date_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', html_content)
    date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y年%m月%d日")
    
    # 提取卡片内容
    cards = re.findall(
        r'<div class="card">.*?<div class="card-title">.*?<a[^>]*>([^<]+)</a>.*?<div class="card-summary">(.*?)</div>',
        html_content, re.DOTALL
    )
    
    if not cards:
        return f"今日报告已更新，请点击查看详情"
    
    # 构建摘要Markdown
    lines = []
    lines.append(f"**📅 {date_str}**")
    lines.append("")
    
    # 最多取前5条最重要的动态
    for i, (title, summary) in enumerate(cards[:5], 1):
        # 清理标题
        title = re.sub(r'<[^>]+>', '', title).strip()
        # 清理摘要中的HTML标签，保留段落
        summary = re.sub(r'<[^>]+>', '', summary).strip()
        summary = re.sub(r'\s+', ' ', summary)
        summary = summary[:100] + "..." if len(summary) > 100 else summary
        
        lines.append(f"**{i}. {title}**")
        lines.append(f"{summary}")
        lines.append("")
    
    return "\n".join(lines)


def build_html_report(cfg: dict, logger: logging.Logger) -> tuple[Path, str]:
    """构建HTML报告，返回文件路径和报告摘要"""
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = REPO_DIR / "index.html"
    template_file = REPO_DIR / "template.html"

    # 读取模板
    if template_file.exists():
        template = read_template(template_file)
    else:
        template = read_template(Path(__file__).parent / "template.html")

    # 扫描今日HTML获取内容
    pdf_dir = cfg["report_dir"]
    today_html = None
    for pattern in [f"医院信息化与AI每日简报_{today}.html", f"日报_{today}.html"]:
        files = list(pdf_dir.glob(pattern))
        if files:
            today_html = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            break

    if today_html:
        # 直接复制今日HTML
        html = today_html.read_text(encoding="utf-8")
        logger.info(f"已使用今日报告：{today_html.name}")
        # 提取摘要供钉钉消息使用
        report_summary = extract_summary_from_html(html)
    else:
        report_summary = f"今日报告已更新，请点击查看详情"
        title_str = f"【广佛医疗行业动态日报 {today}】"
        # 使用模板生成简单页面
        html = template
        html = html.replace("__TITLE__", title_str)
        html = html.replace("__DATE__", today)
        html = html.replace("__COUNT__", "若干")
        html = html.replace("__CONTENT__", f'<div class="card"><p>{report_summary}</p></div>')
        logger.info("未找到今日HTML，使用模板生成")

    report_file.write_text(html, encoding="utf-8")
    logger.info(f"HTML 报告已生成：{report_file.name}")
    return report_file, f"【广佛医疗行业动态日报 {today}】", report_summary


def push_to_github(logger: logging.Logger) -> str:
    """推送仓库到 GitHub，返回页面 URL"""
    logger.info("正在推送到 GitHub…")

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


def send_markdown_card(webhook: str, title: str, summary: str, url: str, keyword: str, logger: logging.Logger):
    """发送 Markdown 卡片消息（带按钮样式链接）"""
    # 标题需要包含关键词
    full_title = f"[{keyword}] {title}" if keyword else title
    
    # Markdown 格式：标题 + 摘要 + 按钮式链接
    markdown_text = f"""## {full_title}

{summary}

[查看完整报告]({url})
"""
    
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": full_title,
            "text": markdown_text
        }
    }

    r = requests.post(webhook, json=payload, timeout=15)
    data = r.json()
    if data.get("errcode") == 0:
        logger.info("[OK] 发送成功！")
    else:
        raise RuntimeError(str(data))


def main():
    parser = argparse.ArgumentParser(description="生成报告 → 推送GitHub → 发送钉钉卡片")
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
        logger.info("等待 GitHub Pages 构建（约 30 秒）…")
        time.sleep(30)

        # Step 3: 获取 token
        token = get_token(cfg["app_key"], cfg["app_secret"], logger)

        # Step 4: 发送到各个群
        enabled_groups = [g for g in cfg["groups"] if g["enabled"]]
        logger.info(f"发送到 {len(enabled_groups)} 个群…")

        success = 0

        for group in enabled_groups:
            keyword = group.get("keyword", "").strip()
            logger.info(f"→ 发送到：【{group['name']}】，关键词：'{keyword}'")
            try:
                send_markdown_card(group["webhook"], report_title, report_summary, page_url, keyword, logger)
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
