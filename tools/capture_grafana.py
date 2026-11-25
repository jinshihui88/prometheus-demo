# -*- coding: utf-8 -*-
"""Grafana 配置与测试结果截图采集（供 Prometheus 教程 md 使用）。

流程：从会话 transcript 提取 Grafana 管理员密码（只在脚本内部使用，不打印、
不落盘明文）-> 登录 -> 数据源配置页截图 -> 点击「保存并测试」采集成功提示
截图 -> Dashboard 五面板总览截图，保存到 docs/images/。

用法：python tools/capture_grafana.py
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

TRANSCRIPT = Path(
    r"C:\Users\Administrator\.workbuddy\projects\d-project\cacfe90b-4311-4ada-8c0a-456ec85a3039.jsonl"
)
OUT_DIR = Path(r"D:\project\prometheus-demo\docs\images")
BASE = "http://localhost:3000"


def extract_password() -> str | None:
    """从会话记录里提取用户提供的 Grafana 密码（不打印明文）。"""
    pat = re.compile(r"用户名\s*[:：]\s*admin\s*密码\s*[:：]\s*([^\s，,。]+)")
    with TRANSCRIPT.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = pat.search(line)
            if m:
                return m.group(1)
    return None


def main() -> int:
    pwd = extract_password()
    if not pwd:
        print("FAIL: 未从 transcript 提取到 Grafana 密码")
        return 1
    print("STEP: 密码提取 OK")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # ---- 登录 ----
        page.goto(BASE + "/login", wait_until="networkidle")
        page.fill('input[name="user"]', "admin")
        page.fill('input[name="password"]', pwd)
        page.click('button[type="submit"]')
        page.wait_for_timeout(3000)
        # 若出现修改密码引导页则跳过
        try:
            skip = page.get_by_role("link", name=re.compile("skip", re.I))
            if skip.count() > 0:
                skip.first.click()
                page.wait_for_timeout(1500)
        except Exception:
            pass
        if "/login" in page.url:
            print("FAIL: Grafana 登录未成功")
            return 1
        print("STEP: 登录 OK ->", page.url)

        # ---- 1) 数据源配置页 ----
        page.goto(
            BASE + "/connections/datasources/edit/eg58sw1ckjwn4b",
            wait_until="networkidle",
        )
        page.wait_for_timeout(2500)
        if "edit" not in page.url:
            print("WARN: 数据源 UID 直达失败，改走列表页:", page.url)
            page.goto(BASE + "/connections/datasources", wait_until="networkidle")
            page.wait_for_timeout(2000)
            link = page.locator("a[href*='/connections/datasources/edit/']").first
            link.click()
            page.wait_for_timeout(2500)
        url_input = page.locator(
            "input[value*='9090'], input[id*='connection-input']"
        )
        print("STEP: 数据源编辑页 OK, URL 输入框数量 =", url_input.count())
        page.screenshot(path=str(OUT_DIR / "grafana_datasource_config.png"))
        saved.append("grafana_datasource_config.png")

        # ---- 2) 保存并测试 -> 成功提示 ----
        test_btn = page.locator(
            "button:has-text('保存并测试'), button:has-text('Save & test')"
        ).first
        test_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        test_btn.click()
        try:
            page.wait_for_selector(
                "text=Successfully queried", timeout=15000
            )
            print("STEP: Save & test 成功提示出现")
        except Exception:
            print("WARN: 未捕获英文成功提示，按当前状态截图")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT_DIR / "grafana_datasource_test_ok.png"))
        saved.append("grafana_datasource_test_ok.png")

        # ---- 3) Dashboard 五面板总览 ----
        page.goto(
            BASE
            + "/d/adpscr4/?from=now-6h&to=now&timezone=browser",
            wait_until="networkidle",
        )
        try:
            page.wait_for_selector(".panel-container", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(6000)  # 等待全部图表渲染完成
        page.screenshot(path=str(OUT_DIR / "grafana_dashboard_overview.png"))
        saved.append("grafana_dashboard_overview.png")

        browser.close()

    print("DONE:", ", ".join(saved))
    return 0


if __name__ == "__main__":
    sys.exit(main())
