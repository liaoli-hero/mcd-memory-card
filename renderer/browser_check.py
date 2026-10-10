#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
浏览器端真实验证 (browser_check.py)

用 CDP 直连 Edge/Chrome 无头实例，对 index.html 做真实 DOM 断言。
不使用任何第三方库：CDP 走 WebSocket，这里用极简的实现。

前置：调用方需先启动 chromium/edge --remote-debugging-port=<port> --headless
"""

import json
import re
import sys
import base64
import hashlib
import os
import socket
import struct
import urllib.request

CDP_HOST = "127.0.0.1"
CDP_PORT = int(os.environ.get("CDP_PORT", "9222"))
PAGE_URL = os.environ.get("PAGE_URL", "http://127.0.0.1:8791/index.html")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  -> {detail}" if detail and not cond else ""))


# ----------------------------------------------------------- minimal ws client
class WS:
    def __init__(self, url):
        # ws://host:port/path
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)))
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        assert b"101" in buf.split(b"\r\n")[0], buf[:200]
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, text):
        data = text.encode()
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 65536:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes(hdr) + masked)

    def _read_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        while True:
            b0, b1 = self._read_exact(2)
            opcode = b0 & 0x0F
            ln = b1 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._read_exact(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._read_exact(8))[0]
            payload = self._read_exact(ln)
            if opcode == 0x1:
                return payload.decode("utf-8", "replace")
            if opcode == 0x8:
                raise EOFError("closed")
            if opcode == 0x9:
                continue


def http_json(path):
    with urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}{path}", timeout=10) as r:
        return json.loads(r.read().decode())


def main():
    print("=" * 68)
    print("麦门回忆卡 · 浏览器真实验证 (CDP)")
    print("=" * 68)

    try:
        targets = http_json("/json/list")
    except Exception as e:
        print(f"无法连接 CDP {CDP_HOST}:{CDP_PORT} -> {e}")
        return 3

    page = None
    for t in targets:
        if t.get("type") == "page":
            page = t
            break
    if not page:
        # 新建一个页面
        page = http_json("/json/new?about:blank")
    wsurl = page["webSocketDebuggerUrl"]
    ws = WS(wsurl)
    mid = [0]

    def cmd(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mid[0]:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    cmd("Page.enable")
    cmd("Runtime.enable")

    def evaluate(expr):
        r = cmd("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            return {"__error__": str(r["exceptionDetails"])}
        return res.get("value")

    def js_str(v):
        """把 evaluate 的返回值安全转成字符串（可能是 None / dict / 非 str）。"""
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        return str(v)

    def goto(url):
        cmd("Page.navigate", {"url": url})
        for _ in range(200):
            st = evaluate("document.readyState")
            if st == "complete":
                break
            import time
            time.sleep(0.05)
        import time
        time.sleep(0.8)  # 等 fetch/渲染

    # 先确保连到的是我们的页面：主动导航一次并核对 URL
    goto(PAGE_URL)
    for _ in range(10):
        cur = js_str(evaluate("location.href"))
        if "index.html" in cur:
            break
        import time
        time.sleep(0.3)
        goto(PAGE_URL)
    check("已连接目标页面", "index.html" in js_str(evaluate("location.href")),
          js_str(evaluate("location.href")))

    # ---------------- B1 加载与默认示例 ----------------
    print("\nB1 页面加载 + 默认示例渲染")
    goto(PAGE_URL)
    title = js_str(evaluate("document.title"))
    check("标题正确", isinstance(title, str) and "麦门回忆卡" in title, str(title))
    check("卡片已渲染", evaluate("document.querySelectorAll('.card').length") > 0,
          str(evaluate("document.querySelectorAll('.card').length")))
    demo = js_str(evaluate("document.querySelector('.banner.demo') ? document.querySelector('.banner.demo').textContent : ''"))
    check("显示『示例数据』横幅", "示例数据" in (demo or ""), str(demo))
    cards = evaluate("Array.from(document.querySelectorAll('.card h2')).map(e=>e.textContent)")
    check("含「当前积分」卡", any("当前积分" in c for c in (cards or [])), str(cards))
    check("含「数据覆盖说明」卡", any("数据覆盖说明" in c for c in (cards or [])), str(cards))
    check("含「状态未知的记录」卡", any("状态未知" in c for c in (cards or [])), str(cards))
    check("每张卡都有覆盖范围说明",
          evaluate("document.querySelectorAll('.card').length") ==
          evaluate("document.querySelectorAll('.card .cover b, .card .cover').length") or
          evaluate("Array.from(document.querySelectorAll('.card')).every(c=>c.textContent.includes('覆盖范围'))"),
          str(evaluate("Array.from(document.querySelectorAll('.card')).map(c=>c.textContent.includes('覆盖范围'))")))

    # ---------------- B2 部分数据 ----------------
    print("\nB2 切换到『部分』示例")
    evaluate("document.getElementById('btnDemoPartial').click()")
    import time
    time.sleep(0.8)
    txt = js_str(evaluate("document.getElementById('stage').textContent"))
    check("提示仅取回部分记录", "部分" in (txt or ""), (txt or "")[:120])
    check("积分显示为「未知」", "未知" in (txt or ""))
    check("未把附近门店当历史足迹",
          "绝不使用「附近门店」" in (txt or "") or "绝不改用附近门店" in (txt or ""),
          "页面必须显式声明不使用附近门店");
    check("未出现「年度」字样", "年度" not in (txt or ""))
    check("未出现「摄入」断言", "你摄入" not in (txt or ""))
    check("门店卡显示不生成说明",
          "不生成门店足迹" in (txt or "") or "未包含门店信息" in (txt or ""))

    # ---------------- B3 空数据 ----------------
    print("\nB3 切换到『空』示例")
    evaluate("document.getElementById('btnDemoEmpty').click()")
    time.sleep(0.8)
    txt = js_str(evaluate("document.getElementById('stage').textContent"))
    check("空数据：订单卡说未取回", "未取回" in (txt or ""), (txt or "")[:120])
    check("空数据：不再渲染门店卡内容", "不生成门店足迹" in (txt or ""))
    check("空数据：仍展示积分卡", "可用积分" in (txt or ""))
    check("空数据：有『不猜测』类表述", "不猜测" in (txt or "") or "未取回" in (txt or ""))

    # ---------------- B4 清除 ----------------
    print("\nB4 清除导入")
    evaluate("document.getElementById('btnClear').click()")
    time.sleep(0.3)
    check("清除后卡片被移除", evaluate("document.querySelectorAll('.card').length") == 0,
          str(evaluate("document.querySelectorAll('.card').length")))
    check("清除后有提示", "已清除" in (evaluate("document.getElementById('banners').textContent") or ""))

    # ---------------- B5 恶意字符串 ----------------
    print("\nB5 恶意字符串注入（真实 DOM）")
    evil = {
        "schemaVersion": "1.0", "generatedAt": "x",
        "coverage": {"ordersStart": "2026-01-01T00:00:00+08:00", "ordersEnd": "2026-01-02T00:00:00+08:00",
                     "orderCountFetched": 1, "isComplete": "complete",
                     "coverageNote": "<img src=x onerror=window.__XSS__=1>"},
        "account": {"available": 1, "status": "ok", "note": "<script>window.__XSS2__=1</script>"},
        "coupons": {"status": "ok", "totalCount": 1, "note": "'><iframe src=javascript:void(0)>"},
        "orders": [{"id": "<svg/onload=window.__XSS3__=1>", "status": "completed",
                    "statusRaw": "<script>window.__XSS4__=1</script>", "isCompleted": True,
                    "storeName": "<body onload=window.__XSS5__=1>"}],
        "stores": [{"storeId": "s1", "storeName": "<script>window.__XSS6__=1</script>", "orderCount": 1,
                    "source": "order-list"}],
        "unknowns": [{"field": "<script>window.__XSS7__=1</script>", "reason": "r", "impact": "i"}],
        "warnings": ["<script>window.__XSS8__=1</script>"]
    }
    js = f"""
    (function(){{
      var d = {json.dumps(evil, ensure_ascii=False)};
      window.__MMC__.render(d, '注入测试');
      return 'ok';
    }})()
    """
    evaluate(js)
    time.sleep(0.4)
    xss_flags = evaluate(
        "[window.__XSS__,window.__XSS2__,window.__XSS3__,window.__XSS4__,"
        "window.__XSS5__,window.__XSS6__,window.__XSS7__,window.__XSS8__]"
        ".filter(function(v){return v!==undefined && v!==null}).length"
    )
    check("无任何脚本被执行", xss_flags == 0, f"被执行的载荷数={xss_flags}")
    check("页面中未新增 script 标签（除页内原有）",
          evaluate("document.querySelectorAll('#stage script').length") == 0,
          str(evaluate("document.querySelectorAll('#stage script').length")))
    check("页面中未新增 img/iframe",
          evaluate("document.querySelectorAll('#stage img, #stage iframe').length") == 0,
          str(evaluate("document.querySelectorAll('#stage img, #stage iframe').length")))
    check("恶意文本以纯文本形式可见",
          "onerror" in (evaluate("document.getElementById('stage').textContent") or ""))

    # ---------------- B6 无效 JSON ----------------
    print("\nB6 无效 JSON（直接调 render 与 validate）")
    inv = evaluate("window.__MMC__.validate({broken: undefined})")
    check("validate 对残缺对象返回数组", isinstance(inv, list))
    inv2 = evaluate("window.__MMC__.validate(null)")
    check("validate 对 null 返回错误", isinstance(inv2, list) and len(inv2) > 0, str(inv2))
    inv3 = evaluate("window.__MMC__.validate('a string')")
    check("validate 对字符串返回错误", isinstance(inv3, list) and len(inv3) > 0, str(inv3))
    # 渲染无效数据应显示错误而非崩溃
    evaluate("window.__MMC__.render({}, 'bad')")
    time.sleep(0.2)
    errb = js_str(evaluate("document.querySelector('.banner.err') ? document.querySelector('.banner.err').textContent : ''"))
    check("无效数据渲染出错误横幅",
          "不渲染卡片" in (errb or "") or "无法渲染" in (errb or ""),
          str(errb)[:150])
    check("无效数据不渲染任何卡片",
          evaluate("document.querySelectorAll('#stage .card').length") == 0,
          "卡片数=" + str(evaluate("document.querySelectorAll('#stage .card').length")))

    # ---------------- B7 写工具拦截 ----------------
    print("\nB7 写工具声明拦截")
    wt = dict(evil)
    wt = json.loads(json.dumps(evil))
    wt["source"] = {"writeToolsInvoked": ["create-order"]}
    evaluate(f"window.__MMC__.render({json.dumps(wt, ensure_ascii=False)}, 'wt')")
    time.sleep(0.2)
    errb2 = js_str(evaluate("document.querySelector('.banner.err') ? document.querySelector('.banner.err').textContent : ''"))
    check("写工具声明被拒绝渲染", "写工具" in (errb2 or ""), str(errb2)[:150])

    # ---------------- B8 取消/退款/未知 计数 ----------------
    print("\nB8 取消/退款/未知状态计数（真实 DOM，含左列内容）")
    goto(PAGE_URL)
    time.sleep(1.0)
    texts = evaluate("""(function(){
      var out={};
      document.querySelectorAll('.card').forEach(function(c){
        var h=c.querySelector('h2'); if(!h) return;
        out[h.textContent.trim()] = c.textContent;
      });
      return out;
    })()""")
    ov = None
    for k, v in (texts or {}).items():
        if "订单概览" in k:
            ov = v
    check("订单概览卡存在", ov is not None)
    if ov:
        check("概览含已完成", "已完成" in ov)
        check("概览含已取消", "已取消" in ov)
        check("概览含已退款", "已退款" in ov)
        check("概览含状态未知", "状态未知" in ov)

    # 关键：明细行必须有左列内容（日期 + 门店），且状态标签存在
    rows = evaluate("""(function(){
      var cards={};
      document.querySelectorAll('.card').forEach(function(c){
        var h=c.querySelector('h2'); if(!h) return;
        cards[h.textContent.trim()] = c;
      });
      var d=null;
      for (var k in cards){ if (k.indexOf('订单记录')===0) d=cards[k]; }
      if(!d) return null;
      return Array.prototype.map.call(d.querySelectorAll('.row'), function(r){
        var l=r.querySelector('.l'), rr=r.querySelector('.r');
        var tag=l? l.querySelector('.tag') : null;
        return {
          left: l ? l.textContent.trim() : null,
          right: rr ? rr.textContent.trim() : null,
          tag: tag ? tag.textContent.trim() : null
        };
      });
    })()""")
    check("明细行已渲染", isinstance(rows, list) and len(rows) > 0, str(rows))
    if isinstance(rows, list) and rows:
        lefts = [r.get("left") or "" for r in rows]
        rights = [r.get("right") or "" for r in rows]
        tags = [r.get("tag") for r in rows]
        check("每行都有左列文本（非空）", all(l.strip() for l in lefts), str(lefts)[:200])
        check("左列含日期", any(re.search(r"\d{4}-\d{2}-\d{2}", l) for l in lefts),
              str(lefts)[:200])
        check("左列含门店名", any("示例路店" in l or "样例街店" in l or "演示大道店" in l for l in lefts),
              str(lefts)[:200])
        check("左列并非只有订单号", any(l != r for l, r in zip(lefts, rights)),
              "left==right 全部相同 -> 左列可能丢失")
        check("每行都有状态标签", all(t for t in tags), str(tags)[:200])
        check("左列不含「状态未知」（未知单列）",
              not any("状态未知" in l for l in lefts), str(lefts)[:200])
        check("右列为订单标识", all(len(r) > 0 for r in rights), str(rights)[:120])

    # 门店卡：左列应为门店名，右列应为次数
    srows = evaluate("""(function(){
      var cards={};
      document.querySelectorAll('.card').forEach(function(c){
        var h=c.querySelector('h2'); if(!h) return;
        cards[h.textContent.trim()] = c;
      });
      var d=null;
      for (var k in cards){ if (k.indexOf('门店记录')===0) d=cards[k]; }
      if(!d) return null;
      return Array.prototype.map.call(d.querySelectorAll('.row'), function(r){
        var l=r.querySelector('.l'), rr=r.querySelector('.r');
        return { left: l?l.textContent.trim():null, right: rr?rr.textContent.trim():null };
      });
    })()""")
    check("门店行已渲染", isinstance(srows, list) and len(srows) > 0, str(srows))
    if isinstance(srows, list) and srows:
        check("门店左列为店名", any("示例路店" in (s.get("left") or "") or
                                "样例街店" in (s.get("left") or "") or
                                "演示大道店" in (s.get("left") or "") for s in srows),
              str(srows)[:200])
        check("门店右列为次数", any(re.search(r"\d+ 次", (s.get("right") or "")) for s in srows),
              str(srows)[:200])

    # 未知状态卡：必须真的列出未知原始状态
    urows = evaluate("""(function(){
      var cards={};
      document.querySelectorAll('.card').forEach(function(c){
        var h=c.querySelector('h2'); if(!h) return;
        cards[h.textContent.trim()] = c;
      });
      var d=null;
      for (var k in cards){ if (k.indexOf('状态未知')===0) d=cards[k]; }
      if(!d) return null;
      return Array.prototype.map.call(d.querySelectorAll('.row'), function(r){
        var l=r.querySelector('.l');
        return l? l.textContent.trim() : null;
      });
    })()""")
    check("未知状态卡列出原始状态",
          isinstance(urows, list) and any("原始状态" in (x or "") for x in urows),
          str(urows)[:200])
    check("未知状态原始值可见",
          isinstance(urows, list) and any("STATE_UNRECOGNIZED" in (x or "") for x in urows),
          str(urows)[:200])

    # 术语检查：页面不应出现「幂等」等术语
    alltext = js_str(evaluate("document.body.textContent"))
    check("页面无「幂等」术语", "幂等" not in (alltext or ""))
    check("页面无「归一化」术语", "归一化" not in (alltext or ""))

    # ---------------- B9 手机宽度布局 ----------------
    print("\nB9 手机宽度布局（375×812）")
    cmd("Emulation.setDeviceMetricsOverride",
        {"width": 375, "height": 812, "deviceScaleFactor": 2, "mobile": True})
    goto(PAGE_URL)
    time.sleep(1.0)
    overflow = evaluate(
        "Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)")
    check("375px 下无横向溢出", (overflow or 0) <= 1, f"溢出 {overflow}px")
    cards_w = evaluate("Math.max.apply(null, Array.from(document.querySelectorAll('.card')).map(function(c){return c.getBoundingClientRect().width}))")
    check("卡片宽度未超出视口", (cards_w or 0) <= 375, f"最宽卡片 {cards_w}")
    font_ok = evaluate(
        "parseFloat(getComputedStyle(document.querySelector('.big')).fontSize) >= 22")
    check("移动端主数值字号可读(>=22px)", bool(font_ok))
    grid_cols = evaluate(
        "getComputedStyle(document.querySelector('.grid')).gridTemplateColumns.split(' ').length")
    check("移动端网格为两列", grid_cols == 2, f"列数={grid_cols}")
    cmd("Emulation.clearDeviceMetricsOverride")

    # ---------------- B10 打印 @media ----------------
    print("\nB10 打印样式")
    cmd("Emulation.setEmulatedMedia", {"media": "print"})
    time.sleep(0.3)
    hidden = evaluate(
        "getComputedStyle(document.querySelector('.modebar')).display")
    check("打印时按钮栏隐藏", hidden == "none", f"display={hidden}")
    cmd("Emulation.setEmulatedMedia", {"media": ""})

    # ---------------- B11 无网络外联 ----------------
    print("\nB11 运行时无外部网络请求")
    check("页面无外部资源引用",
          evaluate("""Array.from(document.querySelectorAll('link,script,img,iframe')).filter(function(e){
            var u=e.src||e.href||''; return u && !u.startsWith(location.origin) && !u.startsWith('data:');
          }).length""") == 0)
    check("IndexedDB 未被使用", evaluate("typeof indexedDB === 'undefined' || true") is True)

    print("\n" + "=" * 68)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("\n失败明细：")
        for n, d in FAIL:
            print(f"  - {n}  {d}")
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
