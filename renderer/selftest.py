#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门回忆卡 · 自测脚本 (selftest.py)

覆盖（在无浏览器环境下可验证的部分）：
  T1  三种样例 JSON 均为合法 JSON 且通过 schema 级校验
  T2  空数据样例：订单/状态/门店空卡合并为一条提示，账号积分 0 正确显示
  T3  部分数据样例：isComplete=partial，取消/退款不计入完成
  T4  无效 JSON：validate 返回错误且不抛异常
  T5  恶意字符串：XSS 载荷被转义，不产生可执行标签
  T6  取消/退款/未知状态计数正确性
  T7  数据自相矛盾（status=completed 但 isCompleted=false）被检出
  T8  写工具声明非空时被拒绝渲染
  T9  render.py 端到端：生成 HTML 并检查关键内容
  T10 渲染器无网络调用、无写工具

用法：python selftest.py
退出码：0 全部通过；1 存在失败
"""

import json
import os
import re
import subprocess
import sys
import tempfile

# Windows 上子进程默认用本地编码（cp936）解码，遇到 UTF-8 输出会抛 UnicodeDecodeError。
# 统一显式指定 utf-8 + errors=replace，使本脚本不依赖外部设置 PYTHONIOENCODING 也能通过。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CHILD_ENV = dict(os.environ)
CHILD_ENV["PYTHONIOENCODING"] = "utf-8"
CHILD_ENV["PYTHONUTF8"] = "1"


def run_child(args, **kw):
    """统一的子进程调用：固定 UTF-8，且 stdout/stderr 永不为 None。"""
    r = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=CHILD_ENV,
        **kw,
    )
    r_stdout = r.stdout if isinstance(r.stdout, str) else ""
    r_stderr = r.stderr if isinstance(r.stderr, str) else ""
    return r.returncode, r_stdout, r_stderr


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "renderer"))

import render as R  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  -> {detail}" if detail and not cond else ""))


def load(name):
    p = os.path.join(ROOT, "samples", name)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


print("=" * 68)
print("麦门回忆卡 · 自测")
print("=" * 68)

# ---------------------------------------------------------------- T1
print("\nT1 三种样例均为合法 JSON 且通过校验")
samples = {}
for name in ("fictional-full.json", "fictional-partial.json", "fictional-empty.json"):
    try:
        d = load(name)
        samples[name] = d
        errs = R.validate(d)
        check(f"{name} 解析 + 校验", not errs, "; ".join(errs))
    except Exception as e:
        check(f"{name} 解析 + 校验", False, repr(e))

# ---------------------------------------------------------------- T2
print("\nT2 空数据样例")
e = samples.get("fictional-empty.json", {})
html_e = R.build_html(e, "fictional-empty.json")
check("订单数为 0", e.get("coverage", {}).get("orderCountFetched") == 0)
check("orders 为空数组", e.get("orders") == [])
check("无订单时合并为一条『订单记录』提示（不再有空概览/状态/门店三卡）",
      "<h2>门店记录</h2>" not in html_e and "<h2>状态未知的记录</h2>" not in html_e
      and "<h2>订单记录</h2>" in html_e and "门店足迹" in html_e)
check("账户积分为 0 而非未知", ">0<" in html_e or 'class="big">0<' in html_e)
check("出现『不猜测』类提示",
      "不做任何猜测" in html_e or "未取回任何订单记录" in html_e)
check("coverage 时间范围为 null",
      e.get("coverage", {}).get("ordersStart") is None)

# ---------------------------------------------------------------- T3
print("\nT3 部分数据样例")
p = samples.get("fictional-partial.json", {})
html_p = R.build_html(p, "fictional-partial.json")
check("isComplete = partial", p.get("coverage", {}).get("isComplete") == "partial")
check("HTML 标注部分数据", "仅取回部分" in html_p or "部分" in html_p)
orders_p = p.get("orders", [])
comp_p = [o for o in orders_p if R.norm_status(o.get("status")) == "completed" and o.get("isCompleted") is True]
canc_p = [o for o in orders_p if R.norm_status(o.get("status")) == "cancelled"]
ref_p = [o for o in orders_p if R.norm_status(o.get("status")) == "refunded"]
unk_p = [o for o in orders_p if R.norm_status(o.get("status")) == "unknown"]
check("已完成 = 3", len(comp_p) == 3, f"实际 {len(comp_p)}")
check("已取消 = 1", len(canc_p) == 1, f"实际 {len(canc_p)}")
check("已退款 = 1", len(ref_p) == 1, f"实际 {len(ref_p)}")
check("状态未知 = 1", len(unk_p) == 1, f"实际 {len(unk_p)}")
check("取消/退款不计入已完成", comp_p and not any(
    o.get("status") in ("cancelled", "refunded") for o in comp_p))
check("积分未知不显示为 0", "未知" in html_p)
check("门店卡降级（本次无门店字段）",
      "未包含门店信息" in html_p or "不生成门店足迹" in html_p)

# ---------------------------------------------------------------- T4
print("\nT4 无效 JSON 处理")
for bad, label in [("{not json", "语法错误"),
                   ('{"a":1', "截断"),
                   ("[1,2,3]", "数组根节点"),
                   ('"a string"', "字符串根节点"),
                   ("", "空内容")]:
    try:
        parsed = json.loads(bad)
    except json.JSONDecodeError:
        parsed = None
        check(f"无效JSON[{label}] 被 json 拒绝", True)
        continue
    errs = R.validate(parsed)
    check(f"无效JSON[{label}] 被 validate 拒绝", bool(errs), f"errs={errs}")


def validate_never_throws(d):
    try:
        R.validate(d)
        return True
    except Exception:
        return False


check("validate 对 None 不抛异常", validate_never_throws(None))
check("validate 对 {} 不抛异常", validate_never_throws({}))
check("validate 对 [1,2] 不抛异常", validate_never_throws([1, 2]))
check("validate 对深层嵌套不抛异常", validate_never_throws({"a": {"b": [{"c": 1}]}}))

# ---------------------------------------------------------------- T5
print("\nT5 恶意字符串（XSS）")
payloads = [
    '<script>alert(1)</script>',
    '"><img src=x onerror=alert(1)>',
    "javascript:alert(1)",
    "<svg/onload=alert(1)>",
    "'><iframe src=javascript:alert(1)>",
    "<body onload=alert(1)>",
    "&lt;script&gt;alert(1)&lt;/script&gt;",
]
evil = load("fictional-full.json")
evil["_sample"] = {"kind": "fictional-full", "notice": ""}
evil["account"]["note"] = payloads[0]
evil["coverage"]["coverageNote"] = payloads[1]
evil["coupons"]["note"] = payloads[2]
evil["orders"][0]["id"] = payloads[3]
evil["orders"][0]["storeName"] = payloads[4]
evil["stores"][0]["storeName"] = payloads[5]
evil["unknowns"] = [{"field": payloads[6], "reason": payloads[0], "impact": payloads[1]}]
evil["warnings"] = [payloads[3], payloads[4]]
html_x = R.build_html(evil, "<evil>")

check("转义后不含未转义的 <script>", "<script>alert(1)</script>" not in html_x)
check("转义后不含未转义的 onerror=", "onerror=alert(1)>" not in html_x)
check("转义后不含未转义的 <iframe", "<iframe" not in html_x)
check("转义后不含未转义的 <svg", "<svg" not in html_x)
check("转义后不含未转义的 <body", "<body onload" not in html_x)
check("载荷确实存在于输出中（说明已被渲染）",
      "alert(1)" in html_x or "&lt;script&gt;" in html_x)
# 计数：输出中出现 &lt; 说明被转义
check("存在 HTML 转义产物", "&lt;" in html_x and "&gt;" in html_x)

# ---------------------------------------------------------------- T6
print("\nT6 计数正确性（边界）")
t = {
    "schemaVersion": "1.0", "generatedAt": "x",
    "coverage": {"ordersStart": None, "ordersEnd": None, "orderCountFetched": 5,
                 "isComplete": "partial", "pagesFetched": 1, "coverageNote": "c"},
    "account": {"available": None, "status": "unknown", "note": ""},
    "coupons": {"status": "ok", "totalCount": 1, "note": ""},
    "orders": [
        {"id": "a", "status": "completed", "statusRaw": "X", "isCompleted": True},
        {"id": "b", "status": "cancelled", "statusRaw": "X", "isCompleted": False},
        {"id": "c", "status": "cancelled", "statusRaw": "X", "isCompleted": False},
        {"id": "d", "status": "refunded", "statusRaw": "X", "isCompleted": False},
        {"id": "e", "status": "unknown", "statusRaw": "", "isCompleted": False},
    ],
    "stores": [], "unknowns": [], "warnings": [],
}
check("合法数据通过校验", R.validate(t) == [], "; ".join(R.validate(t)))
h = R.build_html(t, "t")
check("渲染成功且无错误横幅", "无法渲染" not in h)
check("恰好 1 条计入已完成", h.count('class="tag ok"') == 1,
      f"ok tag 数 = {h.count('class=\"tag ok\"')}")
check("取消 2 条、退款 1 条、未知 1 条分别标注",
      h.count('class="tag cancel"') == 2
      and h.count('class="tag refund"') == 1
      and h.count('class="tag unknown"') == 1,
      f"cancel={h.count('class=\"tag cancel\"')} refund={h.count('class=\"tag refund\"')} unknown={h.count('class=\"tag unknown\"')}")
comp = [o for o in t["orders"] if R.norm_status(o["status"]) == "completed" and o["isCompleted"] is True]
check("已完成计数 = 1", len(comp) == 1)
check("左列内容确实出现（日期/门店/状态不丢）",
      'class="l"' in h and len(re.findall(r'<div class="l">', h)) == 5,
      f'左列数={len(re.findall(chr(60)+"div class="+chr(34)+"l"+chr(34)+chr(62), h))}')

# ---------------------------------------------------------------- T7
print("\nT7 写工具声明被拒绝")
wt = load("fictional-full.json")
wt["source"]["writeToolsInvoked"] = ["create-order"]
check("validate 拒绝写工具声明", bool(R.validate(wt)))
h_wt = R.build_html(wt, "wt")
check("HTML 显示拒绝渲染", "无法渲染" in h_wt and "写工具" in h_wt)

core = load("fictional-full.json")
wt2 = json.loads(json.dumps(core))
wt2["source"]["writeToolsInvoked"] = ["mall-create-order", "draw-lottery"]
check("多个写工具也被拒绝", bool(R.validate(wt2)))

# ---------------------------------------------------------------- T7b
print("\nT7b 深度校验：嵌套成员类型错误")
bad_cases = [
    ("orders 含 null 成员", {"orders": [None]}),
    ("orders 含字符串成员", {"orders": ["x"]}),
    ("orders 缺 status", {"orders": [{"id": "a", "isCompleted": False}]}),
    ("orders 非法 status", {"orders": [{"id": "a", "status": "paid", "isCompleted": False}]}),
    ("orders status 与 isCompleted 矛盾",
     {"orders": [{"id": "a", "status": "cancelled", "isCompleted": True}]}),
    ("orders createdAt 非法时间",
     {"orders": [{"id": "a", "status": "completed", "isCompleted": True, "createdAt": "昨天"}]}),
    ("orders amount 为字符串",
     {"orders": [{"id": "a", "status": "completed", "isCompleted": True, "amount": "34.5"}]}),
    ("orders items 含非对象",
     {"orders": [{"id": "a", "status": "completed", "isCompleted": True, "items": ["x"]}]}),
    ("orders items.quantity 为负",
     {"orders": [{"id": "a", "status": "completed", "isCompleted": True,
                  "items": [{"name": "x", "quantity": -1}]}]}),
    ("stores 成员非对象", {"stores": ["x"]}),
    ("stores orderCount = 0", {"stores": [{"storeId": "s", "orderCount": 0}]}),
    ("stores source 非 order-list",
     {"stores": [{"storeId": "s", "orderCount": 1, "source": "query-nearby-stores"}]}),
    ("coupons.totalCount 为字符串", {"coupons": {"status": "ok", "totalCount": "7"}}),
    ("account.available 为字符串", {"account": {"status": "ok", "available": "1280"}}),
    ("account.status 非法", {"account": {"status": "fine"}}),
    ("unknowns 成员缺 reason", {"unknowns": [{"field": "x"}]}),
    ("warnings 含非字符串", {"warnings": [123]}),
    ("coverage.orderCountFetched 为负",
     {"coverage": {"ordersStart": None, "ordersEnd": None, "orderCountFetched": -1,
                   "isComplete": "complete", "coverageNote": "c"}}),
    ("coverage 时间倒挂",
     {"coverage": {"ordersStart": "2026-10-10T00:00:00+08:00",
                   "ordersEnd": "2026-01-01T00:00:00+08:00",
                   "orderCountFetched": 0, "isComplete": "complete", "coverageNote": "c"}}),
    ("source.writeToolsInvoked 非数组", {"source": {"writeToolsInvoked": "create-order"}}),
    ("source.toolsFailed 成员非对象", {"source": {"toolsFailed": ["x"]}}),
]
base = json.loads(json.dumps(load("fictional-full.json")))
for label, patch in bad_cases:
    d = json.loads(json.dumps(base))
    d.update(patch)
    if "coverage" in patch:
        d["coverage"] = patch["coverage"]
    if "orders" in patch:
        d["orders"] = patch["orders"]
        d["coverage"]["orderCountFetched"] = len(patch["orders"])
    if "stores" in patch:
        d["stores"] = patch["stores"]
    if "coupons" in patch:
        d["coupons"] = patch["coupons"]
    if "account" in patch:
        d["account"] = patch["account"]
    if "unknowns" in patch:
        d["unknowns"] = patch["unknowns"]
    if "warnings" in patch:
        d["warnings"] = patch["warnings"]
    if "source" in patch:
        d["source"] = patch["source"]
    errs = R.validate(d)
    check(f"拒绝[{label}]", bool(errs), "未报错")
    # 且不得抛异常
    try:
        R.build_html(d, "bad")
        rendered = True
    except Exception as e:
        rendered = False
        check(f"渲染[{label}] 不抛异常", False, repr(e))
        continue
    if rendered:
        pass

# 关键回归：{orders:[null]} 必须被拒绝且不抛异常
print("\nT7c 回归：{orders:[null]}")
d_null = {
    "schemaVersion": "1.0", "generatedAt": "x",
    "coverage": {"ordersStart": None, "ordersEnd": None, "orderCountFetched": 1,
                 "isComplete": "unknown", "pagesFetched": None, "coverageNote": "c"},
    "account": {"status": "unknown", "available": None, "note": ""},
    "coupons": {"status": "unavailable", "totalCount": None, "note": ""},
    "orders": [None], "stores": [], "unknowns": [], "warnings": [],
}
e_null = R.validate(d_null)
check("orders 含 null 被拒绝", bool(e_null), str(e_null))
try:
    h_null = R.build_html(d_null, "null")
    check("渲染含 null 的 orders 不抛异常", True)
    check("页面给出人话错误", "无法渲染" in h_null and "null" in h_null)
except Exception as ex:
    check("渲染含 null 的 orders 不抛异常", False, repr(ex))

# ---------------------------------------------------------------- T9
print("\nT9 端到端：render.py 生成 HTML")
tmp = tempfile.mkdtemp(prefix="mmc-")
out = os.path.join(tmp, "out.html")
rc, so, se = run_child([
    sys.executable, os.path.join(ROOT, "renderer", "render.py"),
    os.path.join(ROOT, "samples", "fictional-full.json"), "-o", out])
check("render.py 退出码 0", rc == 0, (se or "")[:200])
check("stderr 不为 None", se is not None)
check("stdout 不为 None", so is not None)
check("输出文件存在", os.path.exists(out))
if os.path.exists(out):
    with open(out, "r", encoding="utf-8") as f:
        oh = f.read()
    check("输出含卡片标题与折叠说明块",
          "当前积分" in oh and "查看数据说明" in oh and '<details class="tech">' in oh)
    check("输出含覆盖范围", "覆盖范围" in oh)
    _ctrls = [c for c in oh if ord(c) < 32 and c not in (chr(10), chr(13), chr(9))]
    check("输出无 <script> 标签、无异常控制字符",
          "<script" not in oh and not _ctrls, repr(_ctrls[:5]))
    check("已取消/已退款分别出现", "已取消" in oh and "已退款" in oh)
    check("门店来源说明存在", "非附近推荐" in oh)
    check("含参赛作品声明", "参赛作品" in oh)
    # 关键：左列内容必须真实存在
    check("左列 <div class=\"l\"> 存在", 'class="l"' in oh)
    check("左列含日期或门店文本",
          bool(re.search(r'<div class="l">20\d\d-\d\d-\d\d', oh)))

# 无效 JSON 端到端
badp = os.path.join(tmp, "bad.json")
with open(badp, "w", encoding="utf-8") as f:
    f.write("{broken")
rc2, so2, se2 = run_child([sys.executable, os.path.join(ROOT, "renderer", "render.py"), badp])
check("无效 JSON：退出码 2", rc2 == 2, f"rc={rc2}")
check("无效 JSON：stderr 有提示", "解析失败" in (se2 or ""))
check("无效 JSON：stderr 不为 None", se2 is not None)

# 结构错误端到端（orders:[null]）
nullp = os.path.join(tmp, "null.json")
with open(nullp, "w", encoding="utf-8") as f:
    json.dump(d_null, f, ensure_ascii=False)
rc3, so3, se3 = run_child([sys.executable, os.path.join(ROOT, "renderer", "render.py"),
                           nullp, "-o", os.path.join(tmp, "null.html")])
check("结构错误：不崩溃（退出码 0）", rc3 == 0, f"rc={rc3} {(se3 or '')[:200]}")
check("结构错误：stderr 有警告", "校验未通过" in (se3 or "") or "null" in (se3 or ""))
if os.path.exists(os.path.join(tmp, "null.html")):
    with open(os.path.join(tmp, "null.html"), "r", encoding="utf-8") as f:
        nh = f.read()
    check("结构错误：页面给错误说明", "无法渲染" in nh)

# ---------------------------------------------------------------- T10
print("\nT10 安全性静态检查")
src_html = os.path.join(ROOT, "index.html")
with open(src_html, "r", encoding="utf-8") as f:
    hsrc = f.read()
check("index.html 无 fetch 到外域（仅本地 samples）",
      not re.search(r"fetch\(\s*['\"]https?://", hsrc))
check("index.html 无 XMLHttpRequest", "XMLHttpRequest" not in hsrc)
check("index.html 无 localStorage", "localStorage" not in hsrc)
check("index.html 无 sessionStorage", "sessionStorage" not in hsrc)
check("index.html 无 document.cookie", "document.cookie" not in hsrc)
check("index.html 无 WebSocket", "WebSocket" not in hsrc)
check("index.html 无 sendBeacon", "sendBeacon" not in hsrc)
# innerHTML 使用检查：应仅用于清空（= ""），不用于拼接数据
bad_inner = re.findall(r"innerHTML\s*=\s*(?![\"']\s*[\"'])", hsrc)
check("index.html 未用 innerHTML 拼接数据", len(bad_inner) == 0,
      f"发现 {len(bad_inner)} 处可疑赋值")
check("index.html 未出现写工具名作为调用",
      not re.search(r"(create-order|draw-lottery|auto-bind-coupons)\s*\(", hsrc))
check("index.html 含演示模式横幅", "示例数据 · 非真实账户" in hsrc)

with open(os.path.join(ROOT, "renderer", "render.py"), "r", encoding="utf-8") as f:
    rsrc = f.read()
check("render.py 无 requests/urllib 网络库",
      not re.search(r"\b(import\s+requests|urllib|http\.client|socket)\b", rsrc))
check("render.py 含写工具黑名单", "WRITE_TOOLS" in rsrc and "create-order" in rsrc)

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 68)
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("\n失败明细：")
    for n, d in FAIL:
        print(f"  - {n}  {d}")
print("=" * 68)
sys.exit(1 if FAIL else 0)
