#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页 JS 内核与 budget_calc.py 的规则一致性对拍（golden test）。

不依赖浏览器：从 index.html 中提取 /*KERNEL-BEGIN*/ ... /*KERNEL-END*/ 之间的
计算内核，交给 Node 的 vm 执行，再与 Python allocate() 逐字段比对。

用法：
    python3 tests/golden_test.py            # 固定边界用例 + 400 组随机用例
    python3 tests/golden_test.py --random 2000
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYOUTS = [
    ("college-budget-planner/web/index.html", "college-budget-planner/scripts"),
    ("01_网页版/index.html", "02_Skill版/scripts"),
]


def locate():
    """兼容仓库结构与参赛包结构。"""
    for html_rel, scripts_rel in LAYOUTS:
        html = os.path.join(ROOT, html_rel)
        scripts = os.path.join(ROOT, scripts_rel)
        if os.path.isfile(html) and os.path.isdir(scripts):
            return html, scripts
    raise SystemExit("未找到网页或脚本目录，请在仓库根或参赛包根目录运行")


HTML, SCRIPTS = locate()
sys.path.insert(0, SCRIPTS)
from budget_calc import allocate as py_allocate  # noqa: E402

KERNEL_RE = re.compile(r"/\*KERNEL-BEGIN\*/(.*?)/\*KERNEL-END\*/", re.S)

NODE_DRIVER = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + '\nthis.allocate = allocate;', ctx);
const out = cases.map(c => {
  const r = ctx.allocate(c.living, c.fixed, c.big, c.month, c.days, c.dorm);
  return {
    mode: r.mode, alloc: r.alloc, remaining: r.R, meal_floor: r.floor,
    total: r.total, balanced: r.balanced, trigger: r.trigger
  };
});
process.stdout.write(JSON.stringify(out));
"""


def fixed_cases():
    base = dict(living=1500, fixed=0, big=200, month=11, days=28, dorm=True)
    cases = []
    for m in range(1, 13):
        cases.append(dict(base, month=m))
    for d in range(20, 32):
        cases.append(dict(base, days=d))
    for dorm in (True, False):
        for living, fixed, big in [
            (1500, 0, 200), (2000, 115, 0), (1000, 0, 0), (800, 0, 0),
            (1200, 75, 300), (1000, 0, 900), (1500, 0, 0), (500, 0, 0),
            (1100, 0, 0), (1160, 0, 0), (1060, 0, 0), (3000, 200, 1000),
            (1500, 0, 20), (1500, 0, 10), (1500, 0, 1490), (1500, 300, 200),
        ]:
            cases.append(dict(base, living=living, fixed=fixed, big=big, dorm=dorm))
    return cases


def random_cases(n, seed=20261112):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(dict(
            living=rng.randrange(400, 4001, 10),
            fixed=rng.randrange(0, 301, 5),
            big=rng.randrange(0, 2001, 10),
            month=rng.randint(1, 12),
            days=rng.randint(20, 31),
            dorm=rng.random() > 0.2,
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=400)
    args = ap.parse_args()

    html = open(HTML, encoding="utf-8").read()
    m = KERNEL_RE.search(html)
    if not m:
        print("FAIL: 未找到 KERNEL 标记，内核无法被提取对拍")
        return 2
    kernel = m.group(1)

    cases = fixed_cases() + random_cases(args.random)
    tmp = tempfile.mkdtemp(prefix="cbp-golden-")
    kpath = os.path.join(tmp, "kernel.js")
    cpath = os.path.join(tmp, "cases.json")
    dpath = os.path.join(tmp, "driver.js")
    open(kpath, "w", encoding="utf-8").write(kernel)
    open(cpath, "w", encoding="utf-8").write(json.dumps(cases))
    open(dpath, "w", encoding="utf-8").write(NODE_DRIVER)

    node = subprocess.run(["node", dpath, kpath, cpath],
                          capture_output=True, text=True)
    if node.returncode != 0:
        print("FAIL: Node 执行内核出错\n" + node.stderr[:2000])
        return 2
    js_results = json.loads(node.stdout)

    fields = ["mode", "remaining", "meal_floor", "total", "balanced", "trigger"]
    bad = []
    for case, js in zip(cases, js_results):
        py = py_allocate(case["living"], case["fixed"], case["big"],
                         case["month"], case["days"], dorm_on=case["dorm"])
        diffs = []
        for f in fields:
            py_key = {"remaining": "remaining", "meal_floor": "meal_floor",
                      "total": "total_check", "trigger": "trigger_large_adjust"}.get(f, f)
            if js[f] != py[py_key]:
                diffs.append("%s: js=%r py=%r" % (f, js[f], py[py_key]))
        for k in ("meal", "daily", "fun", "save", "emg"):
            if js["alloc"][k] != py["alloc"][k]:
                diffs.append("alloc.%s: js=%r py=%r" % (k, js["alloc"][k], py["alloc"][k]))
        if diffs:
            bad.append((case, diffs))

    print("用例总数：%d（固定边界 %d + 随机 %d）"
          % (len(cases), len(cases) - args.random, args.random))
    if bad:
        print("FAIL: %d 组不一致" % len(bad))
        for case, diffs in bad[:8]:
            print("  ", case)
            for d in diffs:
                print("     ", d)
        return 1
    print("PASS: JS 内核与 budget_calc.py 在全部用例上完全一致")
    print("比对字段：mode / 五板块金额 / remaining / meal_floor / total / balanced / trigger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
