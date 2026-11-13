#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校生活费预算计算器（事前预算，非记账）

用法：
  python3 budget_calc.py --living 2000 --fixed 115 --big 0 --month 11
  python3 budget_calc.py --living 1500 --fixed 0 --big 200 --month 11 --json

输出：五板块分配金额、占比、闭合校验、紧预算/大额调整触发标记。
"""
import argparse
import json
import math
import sys

# 月份 -> 季节：6-9 月制冷、12-2 月取暖为空调季，其余过渡季
SEASON = {1: "peak", 2: "peak", 3: "off", 4: "off", 5: "off",
          6: "peak", 7: "peak", 8: "peak", 9: "peak", 10: "off", 11: "off", 12: "peak"}
SEASON_NAME = {"peak": "空调季", "off": "过渡季"}
DORM_FEE = {"peak": 160, "off": 120}
DORM_DETAIL = {
    "off": {"洗澡热水": 40, "饮用水": 25, "洗衣": 25, "电费": 30},
    "peak": {"洗澡热水": 45, "饮用水": 25, "洗衣": 30, "电费": 60},
}

RATIO = {"meal": 0.52, "daily": 0.10, "fun": 0.18, "save": 0.12, "emg": 0.08}
MEAL_PER_DAY = 30  # 早 6 + 午 12 + 晚 12
LABELS = {"meal": "三餐伙食", "daily": "日常零碎", "fun": "娱乐社交",
          "save": "储蓄", "emg": "应急备用金"}


def round10(x):
    """四舍五入到 10 元，避开 Python 银行家舍入。"""
    return int(x / 10.0 + 0.5 + 1e-9) * 10


def ceil10(x):
    """向上取整到 10 元。下限必须向上取整，否则四舍五入会把 6% 压到 5.9%。"""
    return int(math.ceil(x / 10.0 - 1e-9)) * 10


def _move_to_emg(parts, emg, target):
    """从 fun -> daily -> save 依次挪钱给应急金，返回 (parts, emg, 缺口)。"""
    need = target - emg
    for key in ("fun", "daily", "save"):
        if need <= 0:
            break
        take = min(need, parts[key])
        parts[key] -= take
        need -= take
        emg += take
    return parts, emg, need


def allocate(living, fixed_extra, big, month, days, dorm_on=True):
    season = SEASON[month]
    dorm = DORM_FEE[season] if dorm_on else 0
    fixed = fixed_extra + dorm
    remaining = living - fixed - big
    meal_floor = days * MEAL_PER_DAY
    warnings = []
    triggers = []
    alloc = {"meal": 0, "daily": 0, "fun": 0, "save": 0, "emg": 0}

    if remaining <= 0:
        mode = "deficit"
        warnings.append("扣除固定开销与大额支出后已无余额，本月方案不可行，须调整大额支出")
    elif remaining < meal_floor:
        mode = "meal_deficit"
        alloc["meal"] = remaining
        warnings.append("可分配 %d 元低于三餐下限 %d 元，缺口 %d 元；"
                        "严禁借贷填补，建议削减大额支出或增加收入来源"
                        % (remaining, meal_floor, meal_floor - remaining))
    elif remaining < meal_floor + 100:
        mode = "extreme_tight"
        alloc["meal"] = meal_floor
        alloc["emg"] = remaining - meal_floor
        warnings.append("极端紧预算：仅保三餐与少量应急，娱乐、储蓄、日常零碎归零")
    elif remaining < meal_floor * 1.25:
        mode = "tight"
        alloc["meal"] = meal_floor
        alloc["daily"] = 50
        alloc["emg"] = max(0, remaining - meal_floor - 50)
        warnings.append("紧预算模式：娱乐与储蓄归零，日常零碎压到 50 元")
    else:
        mode = "normal"
        meal = round10(remaining * RATIO["meal"])
        if meal < meal_floor:
            # 下限保护：三餐先补到下限，余下按四块权重归一化再分
            meal = meal_floor
            rest = remaining - meal
            # 用整数权重，避免 0.10+0.18+0.12+0.08 = 0.48000000000000004 的浮点累加误差
            parts = {
                "daily": round10(rest * 10 / 48),
                "fun": round10(rest * 18 / 48),
                "save": round10(rest * 12 / 48),
            }
            emg = rest - parts["daily"] - parts["fun"] - parts["save"]
            emg_min = ceil10(remaining * 0.06)
            if emg < emg_min:
                parts, emg, left = _move_to_emg(parts, emg, emg_min)
                if left > 0:
                    warnings.append("应急备用金仍低于可分配金额的 6%，其余板块已无可压缩空间")
            warnings.append("按 52%% 分配三餐不足三餐下限 %d 元，已按下限保护并压缩其余板块" % meal_floor)
            alloc = {"meal": meal, "daily": parts["daily"], "fun": parts["fun"],
                     "save": parts["save"], "emg": emg}
        else:
            daily = round10(remaining * RATIO["daily"])
            fun = round10(remaining * RATIO["fun"])
            save = round10(remaining * RATIO["save"])
            emg = remaining - meal - daily - fun - save
            parts = {"daily": daily, "fun": fun, "save": save}
            emg_min = ceil10(remaining * 0.06)
            emg_max = round10(remaining * 0.10)
            if emg < emg_min:
                parts, emg, left = _move_to_emg(parts, emg, emg_min)
                if left > 0:
                    warnings.append("应急备用金仍低于可分配金额的 6%")
            if emg > emg_max > 0:
                parts["save"] += emg - emg_max
                emg = emg_max
            alloc = {"meal": meal, "daily": parts["daily"], "fun": parts["fun"],
                     "save": parts["save"], "emg": emg}

    # 大额支出调整方案的触发判断
    if living > 0:
        if fixed + big > living * 0.7:
            triggers.append("固定开销+大额支出超过生活费 70%")
        if mode in ("deficit", "meal_deficit", "extreme_tight", "tight"):
            triggers.append("三餐被压到下限或已进入紧预算模式")
        if mode == "normal" and remaining * RATIO["meal"] < meal_floor:
            triggers.append("按 52% 分配三餐不足下限，实际挤压了吃饭")
        if alloc["save"] + alloc["emg"] < living * 0.1:
            triggers.append("储蓄+应急合计低于生活费 10%")

    total = sum(alloc.values()) + fixed + big
    result = {
        "input": {"living": living, "fixed_extra": fixed, "big": big,
                  "month": month, "days": days},
        "season": SEASON_NAME[season],
        "dorm_fee": dorm,
        "dorm_detail": DORM_DETAIL[season],
        "fixed_total": fixed,
        "big": big,
        "remaining": remaining,
        "meal_floor": meal_floor,
        "mode": mode,
        "alloc": alloc,
        "ratio_pct": {k: round(v * 100.0 / living, 1) if living else 0.0
                      for k, v in alloc.items()},
        "fixed_pct": round(fixed * 100.0 / living, 1) if living else 0.0,
        "big_pct": round(big * 100.0 / living, 1) if living else 0.0,
        "total_check": total,
        "balanced": total == living,
        "trigger_large_adjust": bool(triggers),
        "triggers": triggers,
        "warnings": warnings,
    }
    return result


def render(res):
    inp = res["input"]
    lines = []
    lines.append("生活费 %d 元｜固定开销 %d 元（宿舍杂费 %d 含在内，%s）｜大额支出 %d 元"
                 % (inp["living"], res["fixed_total"], res["dorm_fee"],
                    res["season"], res["big"]))
    if res["dorm_fee"] > 0:
        d = " / ".join("%s %d" % (k, v) for k, v in res["dorm_detail"].items())
        lines.append("宿舍杂费明细：%s = %d" % (d, res["dorm_fee"]))
    lines.append("可分配剩余 R = %d 元｜三餐下限 = %d 天 × %d = %d 元｜模式 = %s"
                 % (res["remaining"], inp["days"], MEAL_PER_DAY,
                    res["meal_floor"], res["mode"]))
    lines.append("")
    lines.append("%-8s %8s %8s" % ("板块", "金额", "占比"))
    for k in ("meal", "daily", "fun", "save", "emg"):
        lines.append("%-8s %8d %7.1f%%" % (LABELS[k], res["alloc"][k], res["ratio_pct"][k]))
    lines.append("%-8s %8d %7.1f%%" % ("固定开销", res["fixed_total"], res["fixed_pct"]))
    lines.append("%-8s %8d %7.1f%%" % ("大额支出", res["big"], res["big_pct"]))
    lines.append("合计 %d 元｜闭合校验：%s"
                 % (res["total_check"], "通过" if res["balanced"] else "不通过，需重算"))
    if res["trigger_large_adjust"]:
        lines.append("触发大额支出调整方案：" + "；".join(res["triggers"]))
    else:
        lines.append("未触发大额支出调整方案：本月大额不构成压力")
    for w in res["warnings"]:
        lines.append("提示：" + w)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="高校生活费预算计算器")
    ap.add_argument("--living", type=int, required=True, help="每月生活费（元）")
    ap.add_argument("--fixed", type=int, default=0,
                    help="除宿舍杂费外的固定开销总额（话费+交通+校园网+订阅），无则填 0")
    ap.add_argument("--big", type=int, default=0, help="本月大额支出（元），无则填 0")
    ap.add_argument("--month", type=int, default=11, help="月份 1-12，用于判定空调季/过渡季")
    ap.add_argument("--days", type=int, default=28, help="在校天数，默认 28")
    ap.add_argument("--no-dorm", action="store_true", help="宿舍杂费不由本人承担时加上该参数")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.living <= 0:
        print("错误：--living 必须为正整数", file=sys.stderr)
        return 2
    if not 1 <= args.month <= 12:
        print("错误：--month 必须在 1-12 之间", file=sys.stderr)
        return 2
    if not 20 <= args.days <= 31:
        print("错误：--days 建议在 20-31 之间", file=sys.stderr)
        return 2

    res = allocate(args.living, args.fixed, args.big, args.month, args.days,
                   dorm_on=not args.no_dorm)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(render(res))
    return 0 if res["balanced"] else 1


if __name__ == "__main__":
    sys.exit(main())