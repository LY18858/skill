#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""针对本轮评审项的浏览器行为验证：XSS、flash 副作用、占比闭合、chips、深色、aria。"""
import os
import sys
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _web_rel():
    for rel in ("college-budget-planner/web/index.html", "01_网页版/index.html"):
        if os.path.isfile(os.path.join(ROOT, rel)):
            return rel
    raise SystemExit("未找到网页目录")


BASE = "http://localhost:8765/" + _web_rel()
CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"
PAYLOAD = '<img src=x onerror="window.__xss=1">'
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (("  " + detail) if detail else ""))


def boot(page):
    page.goto(BASE, wait_until="networkidle")
    page.evaluate("localStorage.clear()")
    page.reload(wait_until="networkidle")


def main():
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME,
                              args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = b.new_page(viewport={"width": 1440, "height": 960})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))

        # 1) XSS：直接注入 + localStorage 持久化后再注入
        boot(pg)
        pg.fill("#bigName", PAYLOAD)
        pg.fill("#big", "200")
        pg.click("#go")
        pg.wait_for_timeout(250)
        check("XSS 注入后不执行脚本", pg.evaluate("window.__xss === undefined"))
        check("XSS 注入后未生成真实 <img> 节点",
              pg.evaluate("document.querySelectorAll('#result img').length") == 0)
        body_text = pg.inner_text("#result")
        check("恶意串按纯文本显示", PAYLOAD in body_text)
        pg.click("#saveBtn")
        pg.wait_for_timeout(200)
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(300)
        check("localStorage 恢复后仍不执行", pg.evaluate("window.__xss === undefined"))
        check("localStorage 恢复后仍无 <img> 节点",
              pg.evaluate("document.querySelectorAll('#result img').length") == 0)
        check("aria-live 已标注", pg.get_attribute("#result", "aria-live") == "polite")

        # 2) 占比最大余项法：各行加和必须等于 100.0%
        for living, fixed, big in [(1500, 0, 200), (2000, 115, 0), (1200, 75, 300), (1730, 65, 240)]:
            boot(pg)
            pg.fill("#living", str(living))
            pg.fill("#phone", str(fixed))
            pg.fill("#big", str(big))
            pg.click("#go")
            pg.wait_for_timeout(200)
            vals = pg.eval_on_selector_all(
                "#result table tbody tr:not(.sum) .pc-cell .num",
                "els => els.map(e => parseFloat(e.textContent))")
            total = round(sum(vals), 1)
            check("占比加和=100.0%%（%d/%d/%d）" % (living, fixed, big),
                  abs(total - 100.0) < 0.001, "实际 %.1f" % total)

        # 3) chips 选中态与手动输入的联动
        boot(pg)
        pg.click('button.chip[data-name="耳机"]')
        pg.wait_for_timeout(200)
        check("chip 点击后高亮", pg.eval_on_selector(
            'button.chip[data-name="耳机"]', "e => e.classList.contains('on')"))
        check("chip 点击后金额写入", pg.input_value("#big") == "300")
        pg.fill("#big", "200")
        pg.wait_for_timeout(200)
        check("手动改金额后取消高亮", pg.eval_on_selector(
            'button.chip[data-name="耳机"]', "e => !e.classList.contains('on')"))

        # 4) flash 副作用：移动端导出按钮的 wide-only 必须存活
        m = b.new_page(viewport={"width": 390, "height": 844})
        boot(m)
        m.click("#go")
        m.wait_for_timeout(200)
        m.click("#exportBtn")
        m.wait_for_timeout(1800)
        html = m.inner_html("#exportBtn")
        check("flash 后 wide-only 结构保留", "wide-only" in html)
        check("flash 后导出文案恢复", "导出" in m.inner_text("#exportBtn"))
        check("aria-invalid 已标注", m.get_attribute("#living", "aria-invalid") is not None)

        # 5) 深色模式三态切换与持久化
        boot(m)
        seq = []
        for _ in range(3):
            m.click("#themeBtn")
            m.wait_for_timeout(120)
            seq.append((m.evaluate("localStorage.getItem('cbp-theme')"),
                        m.get_attribute("html", "data-theme")))
        check("主题三态循环 auto→light→dark→auto",
              [x[0] for x in seq] == ["light", "dark", "auto"], str(seq))
        check("切到深色时 data-theme 同步", seq[1][1] == "dark")
        m.evaluate("localStorage.setItem('cbp-theme','dark')")
        m.reload(wait_until="networkidle")
        m.wait_for_timeout(200)
        check("深色偏好可持久化", m.get_attribute("html", "data-theme") == "dark")
        m.screenshot(path="/tmp/dark_mobile.png", full_page=True)

        # 5.1) 首次引导：显示、关闭、记忆
        boot(pg)
        check("首次访问显示引导", pg.is_visible("#onboard"))
        pg.click("#onboardClose")
        pg.wait_for_timeout(150)
        check("引导关闭后记录标记",
              pg.evaluate("localStorage.getItem('cbp-onboarded')") == "1")
        pg.reload(wait_until="networkidle")
        pg.wait_for_timeout(200)
        check("再次访问不再出现引导", not pg.is_visible("#onboard"))

        # 5.2) 卡片折叠：默认收起次要卡片，可展开
        boot(pg)
        pg.click("#go")
        pg.wait_for_timeout(250)
        check("默认折叠 2 张次要卡片",
              pg.eval_on_selector_all("#result .card.collapsed", "e => e.length") == 2)
        pg.click('#result .fold[data-fold="saving"]')
        pg.wait_for_timeout(150)
        check("点击可展开省钱建议",
              pg.get_attribute('#result .fold[data-fold="saving"]', "aria-expanded") == "true")
        check("展开后正文可见", pg.evaluate("""() => {
            const b = document.querySelector('#result .fold[data-fold="saving"]');
            return getComputedStyle(b.closest('.card').querySelector('.card-body')).display !== 'none';
        }"""))
        body_visible = pg.eval_on_selector_all(
            "#result .card", "els => els.map(e => e.querySelector('.card-body') ? "
                              "getComputedStyle(e.querySelector('.card-body')).display : 'none')")
        check("展开的卡片正文已渲染", "none" in body_visible and body_visible.count("none") == 1,
              str(body_visible))

        # 5.3) 更新提示：输入变化后出现 toast
        boot(pg)
        pg.click("#go")
        pg.wait_for_timeout(200)
        pg.fill("#living", "1650")
        pg.wait_for_timeout(450)
        check("输入变化后弹出更新提示",
              pg.eval_on_selector("#toast", "e => e.classList.contains('show')"))
        check("提示文案正确", "已按最新输入更新" in pg.inner_text("#toast"))

        # 5.4) 预设选中态：默认 chip 与默认值一致
        check("默认 chip 处于选中态",
              pg.eval_on_selector('button.chip[data-name="手表"]', "e => e.classList.contains('on')"))

        # 6) input 事件不应重复触发两次渲染
        boot(pg)
        pg.evaluate("window.__renders = 0; const r = document.getElementById('result');"
                    "new MutationObserver(() => window.__renders++).observe(r, {childList:true});")
        pg.fill("#living", "1600")
        pg.wait_for_timeout(300)
        n = pg.evaluate("window.__renders")
        check("单次输入只触发一次结果重绘", n == 1, "实际 %d 次" % n)

        check("浏览器无 JS 异常", not errors, " | ".join(errors[:2]))
        b.close()

    failed = [r for r in results if not r[1]]
    print("\n合计 %d 项，失败 %d 项" % (len(results), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
