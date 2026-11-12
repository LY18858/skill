import json
import os
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8765/college-budget-planner/web/index.html"
SKILL = "/workspace/college-budget-planner/scripts/budget_calc.py"
CHROME = "/root/.cache/ms-playwright/chromium-1243/chrome-linux/chrome"
SHOT = "/workspace/shots"

CASES = [
    dict(tag="1500/手表200/11月", living=1500, phone=0, traffic=0, net=0, sub=0,
         big=200, month="11", days=28, dorm=True, name="手表"),
    dict(tag="2000/常规/11月", living=2000, phone=40, traffic=50, net=25, sub=0,
         big=0, month="11", days=28, dorm=True, name=""),
    dict(tag="1000/低保/11月", living=1000, phone=0, traffic=0, net=0, sub=0,
         big=0, month="11", days=28, dorm=True, name=""),
    dict(tag="1200/手机300/7月空调季", living=1200, phone=30, traffic=20, net=25, sub=0,
         big=300, month="7", days=28, dorm=True, name="手机"),
    dict(tag="1500/手表200/24天/免宿舍费", living=1500, phone=0, traffic=0, net=0, sub=0,
         big=200, month="11", days=24, dorm=False, name="手表"),
    dict(tag="800/极端缺口", living=800, phone=0, traffic=0, net=0, sub=0,
         big=0, month="11", days=28, dorm=True, name=""),
]


def expected(c):
    cmd = [sys.executable, SKILL, "--living", str(c["living"]),
           "--fixed", str(c["phone"] + c["traffic"] + c["net"] + c["sub"]),
           "--big", str(c["big"]), "--month", c["month"], "--days", str(c["days"]), "--json"]
    if not c["dorm"]:
        cmd.append("--no-dorm")
    return json.loads(subprocess.check_output(cmd, text=True))


def fill(page, c):
    page.goto(BASE, wait_until="networkidle")
    page.evaluate("localStorage.clear()")
    page.reload(wait_until="networkidle")
    page.fill("#living", str(c["living"]))
    page.fill("#phone", str(c["phone"]))
    page.fill("#traffic", str(c["traffic"]))
    page.fill("#net", str(c["net"]))
    page.fill("#sub", str(c["sub"]))
    page.fill("#big", str(c["big"]))
    page.fill("#bigName", c["name"])
    page.fill("#days", str(c["days"]))
    page.select_option("#month", c["month"])
    if not c["dorm"]:
        page.uncheck("#dormOn")
    page.click("#go")
    page.wait_for_timeout(220)


def read_amounts(page):
    rows = page.eval_on_selector_all("#result table tbody tr", """rows => rows.map(tr => {
        const td = tr.querySelector('td');
        const amt = tr.querySelector('td.amt');
        return [td ? td.innerText.trim() : '', amt ? amt.innerText.trim() : ''];
    })""")
    out = {}
    for name, amt in rows:
        if not amt:
            continue
        val = int(amt.replace(",", ""))
        for key in ["三餐伙食", "日常零碎", "娱乐社交", "储蓄", "应急备用金"]:
            if name.startswith(key):
                out[key] = val
        if name.startswith("合计"):
            out["合计"] = val
    return out


def main():
    os.makedirs(SHOT, exist_ok=True)
    ok = True
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = b.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=2)
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        print("=== 数值一致性（页面 vs 脚本）===")
        for c in CASES:
            fill(page, c)
            got = read_amounts(page)
            exp = expected(c)
            want = {k: exp["alloc"][m] for k, m in
                    [("三餐伙食", "meal"), ("日常零碎", "daily"), ("娱乐社交", "fun"),
                     ("储蓄", "save"), ("应急备用金", "emg")]}
            want["合计"] = exp["input"]["living"]
            diff = {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v}
            match = not diff
            ok = ok and match
            print(("PASS " if match else "FAIL ") + c["tag"])
            if diff:
                print("   差异:", diff)

        print("\n=== 交互检查 ===")
        fill(page, CASES[0])
        page.click("#saveBtn")
        page.wait_for_timeout(200)
        saved = page.evaluate("!!localStorage.getItem('cbp-state')")
        print("保存到本地存储:", "OK" if saved else "失败")
        page.click("#reset")
        page.wait_for_timeout(250)
        after = page.input_value("#living")
        print("重置恢复默认:", "OK" if after == "1500" else "异常(" + after + ")")
        ok = ok and saved and after == "1500"

        print("\n=== 控制台 ===")
        print("无报错" if not errors else "报错: " + " | ".join(errors[:3]))
        ok = ok and not errors

        # 截图（长截图时关闭 sticky，避免表单错位）
        fill(page, CASES[0])
        page.evaluate("document.querySelector('.form-panel').style.position='static'")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(SHOT, "desktop.png"), full_page=True)

        m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        fill(m, CASES[0])
        m.evaluate("document.querySelector('.form-panel').style.position='static'")
        m.wait_for_timeout(300)
        m.screenshot(path=os.path.join(SHOT, "mobile.png"), full_page=True)

        b.close()
    print("\n结果:", "全部通过" if ok else "存在问题")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())