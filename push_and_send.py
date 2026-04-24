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
    """将 HTML 报告转换为 Markdown，返回 (标题, MD正文)
    
    MD 格式：
        **文件名（加粗）**
        **【行业动态】**
        1. **标题**：摘要（第一句）
        ...
        **【标杆案例】**
        1. **标题**：摘要（第一句）
        ...
    同时将 MD 文件保存到仓库目录。
    """
    
    # 标题：文件名去掉 .html 后缀
    title = filename.replace(".html", "") if filename else "医院信息化与AI每日简报"
    
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
    
    # 按 section-header 位置切分
    header_positions = [(m.start(), m.group()) for m in re.finditer(r'<div class="section-header \w+">', html_content)]
    
    def get_section_html(cls: str) -> str:
        idx = next((i for i, (_, h) in enumerate(header_positions) if cls in h), None)
        if idx is None:
            return ""
        start = header_positions[idx][0]
        end = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(html_content)
        return html_content[start:end]
    
    md_lines = [f"**{title}**", ""]
    
    # 行业动态
    dynamics_html = get_section_html("dynamics")
    if dynamics_html:
        cards = re.findall(card_pattern, dynamics_html, re.DOTALL)
        md_lines.append("**【行业动态】**")
        for i, (card_title, card_summary) in enumerate(cards, 1):
            card_title = strip_html(card_title)
            card_summary = strip_html(card_summary)
            md_lines.append(f"{i}. **{card_title}**：{first_sentence(card_summary)}")
    
    # 标杆案例
    case_html = get_section_html("case")
    if case_html:
        cards = re.findall(card_pattern, case_html, re.DOTALL)
        md_lines.append("")
        md_lines.append("**【标杆案例】**")
        for i, (card_title, card_summary) in enumerate(cards, 1):
            card_title = strip_html(card_title)
            card_title = re.sub(r'^【标杆案例】', '', card_title).strip()
            card_summary = strip_html(card_summary)
            md_lines.append(f"{i}. **{card_title}**：{first_sentence(card_summary)}")
    
    if len(md_lines) <= 2:
        date_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', html_content)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y年%m月%d日")
        md_content = f"**{title}**\n\n{date_str} 报告已更新，请点击查看详情。"
    else:
        md_content = "\n".join(md_lines)
    
    return (title, md_content)


def read_md_summary(report_dir: Path, logger: logging.Logger) -> tuple[str, str]:
    """读取钉钉摘要MD文件，返回 (标题, MD正文)"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 扫描钉钉摘要MD文件
    for pattern in [f"*钉钉摘要_{today}.md", f"*摘要_{today}.md"]:
        files = list(report_dir.glob(pattern))
        if files:
            md_file = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            content = md_file.read_text(encoding="utf-8")
            
            # 提取标题（第一行去掉#）
            lines = content.strip().split('\n')
            title = lines[0].lstrip('#').strip() if lines else f"医院信息化与AI每日简报_{today}"
            
            logger.info(f"已读取钉钉摘要MD文件：{md_file.name}")
            return (title, content)
    
    logger.warning(f"未找到钉钉摘要MD文件，将从HTML提取")
    return ("", "")


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
    
    # 3. 优先读取钉钉摘要MD文件，如果没有则从HTML提取
    report_title, report_summary = read_md_summary(report_dir, logger)
    if not report_summary:
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
