#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦门回忆卡 · 本地渲染脚本 (render.py)

作用：把一份「已归一化」的 JSON 渲染成一张静态 HTML 卡片页，便于截图与留档。

设计约束（重要）：
  - 本脚本 **不联网**、**不调用任何 MCP 工具**、**不读取任何账号或密钥**。
  - 本脚本 **不假定官方返回结构**。它只消费本项目的归一化 schema。
    从官方原始响应到归一化 JSON 的转换，由 Skill（在 WorkBuddy 内）
    按实际观察到的字段完成，转换规则必须写入 unknowns/note 以便追溯。
  - 未知值一律渲染为「未知」，绝不渲染成 0。
  - 已取消 / 已退款不计入已完成订单；未知状态独立成段。

用法：
    python render.py <归一化JSON> [-o 输出HTML]
    python render.py samples/fictional-full.json -o out.html

仅使用标准库。
"""

import json
import os
import sys
import argparse
import html
from datetime import datetime, timezone

UNKNOWN = "未知"

STATUS_ZH = {
    "completed": "已完成",
    "cancelled": "已取消",
    "refunded": "已退款",
    "unknown": "状态未知",
}
STATUS_CLASS = {
    "completed": "ok",
    "cancelled": "cancel",
    "refunded": "refund",
    "unknown": "unknown",
}

WRITE_TOOLS = {
    "delivery-create-address", "create-order", "cancel-order", "auto-bind-coupons",
    "mall-create-order", "draw-lottery", "party-order-create",
}


# ---------------------------------------------------------------- helpers

def esc(v):
    """所有进入 HTML 的字符串都必须过这里，防注入。"""
    if v is None:
        return UNKNOWN
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return html.escape(f"{v:,}")
    return html.escape(str(v))


def num(v):
    return f"{v:,}" if isinstance(v, (int, float)) and not isinstance(v, bool) else UNKNOWN


def norm_status(s):
    return s if s in ("completed", "cancelled", "refunded") else "unknown"


def fmt_time(iso):
    if not isinstance(iso, str) or not iso:
        return UNKNOWN
    try:
        s = iso.replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return UNKNOWN


def fmt_date(iso):
    if not isinstance(iso, str) or not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        return datetime.fromisoformat(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def cover_text(cov, include_note=True):
    if not isinstance(cov, dict):
        return "未取回订单记录，无法确定覆盖范围"
    if include_note and isinstance(cov.get("coverageNote"), str) and cov["coverageNote"]:
        return cov["coverageNote"]
    s, e = fmt_date(cov.get("ordersStart")), fmt_date(cov.get("ordersEnd"))
    n = cov.get("orderCountFetched") if isinstance(cov.get("orderCountFetched"), int) else 0
    if not n:
        return "未取回订单记录，无法确定覆盖范围"
    completeness = " · 仅本次记录，未确认完整历史" if cov.get("isComplete") != "complete" else ""
    if s and e:
        return f"数据覆盖：{s} 至 {e} · 共取回 {n} 条订单记录" + completeness
    return f"共取回 {n} 条订单记录（时间范围无法确定）" + completeness


# ---------------------------------------------------------------- validation

# 合法状态集合
VALID_STATUS = ("completed", "cancelled", "refunded", "unknown")
VALID_ACCT_STATUS = ("ok", "unknown", "unavailable")
VALID_COMPLETE = ("complete", "partial", "unknown")


def _is_num_or_none(v):
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool))


def _parse_iso(v):
    if not isinstance(v, str) or not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        return None


def validate(data):
    """深度校验。返回人类可读的错误列表；空列表表示通过。

    原则：宁可拒绝渲染，也不在数据错误时输出看似正常的卡片。
    """
    errs = []
    if not isinstance(data, dict):
        return ["根节点不是一个 JSON 对象——顶层应该是一个带花括号的对象。"]

    # ---- 顶层版本
    sv = data.get("schemaVersion")
    if not isinstance(sv, str) or not sv:
        errs.append("缺少 schemaVersion 字段，无法确认数据版本。")
    elif str(sv).split(".")[0] != "1":
        errs.append(f"schemaVersion 为 {sv}，主版本不是 1，本渲染器可能不兼容。")

    # ---- _sample（可选）
    if "_sample" in data and not isinstance(data["_sample"], dict):
        errs.append("_sample 必须是对象（或删除该字段）。")

    # ---- generatedAt（可选但若存在须可解析）
    ga = data.get("generatedAt")
    if ga is not None and not isinstance(ga, str):
        errs.append("generatedAt 必须是字符串。")

    # ---- source
    src = data.get("source")
    if src is not None and not isinstance(src, dict):
        errs.append("source 必须是对象。")
    if isinstance(src, dict):
        if "tools" in src and not isinstance(src["tools"], list):
            errs.append("source.tools 必须是数组。")
        tf = src.get("toolsFailed")
        if tf is not None:
            if not isinstance(tf, list):
                errs.append("source.toolsFailed 必须是数组。")
            else:
                for i, item in enumerate(tf):
                    if not isinstance(item, dict):
                        errs.append(f"source.toolsFailed[{i}] 必须是对象（含 tool 与 reason）。")
                    elif not isinstance(item.get("tool"), str):
                        errs.append(f"source.toolsFailed[{i}].tool 必须是字符串。")
        wt = src.get("writeToolsInvoked")
        if wt is not None:
            if not isinstance(wt, list):
                errs.append("source.writeToolsInvoked 必须是数组（无写操作时请留空数组）。")
            elif wt:
                errs.append("数据声明调用了写工具（" + "、".join(str(x) for x in wt)
                            + "）。本项目仅做只读回顾，已拒绝渲染。")

    # ---- coverage
    cov = data.get("coverage")
    if not isinstance(cov, dict):
        errs.append("缺少 coverage 段，无法确定数据覆盖范围。")
    else:
        for k in ("ordersStart", "ordersEnd"):
            v = cov.get(k)
            if v is not None and _parse_iso(v) is None:
                errs.append(f"coverage.{k} 不是可解析的 ISO 时间：{str(v)[:40]!r}")
        n = cov.get("orderCountFetched")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append("coverage.orderCountFetched 必须是 >= 0 的整数。")
        ic = cov.get("isComplete")
        if ic is not None and ic not in VALID_COMPLETE:
            errs.append(f"coverage.isComplete 取值必须是 {VALID_COMPLETE} 之一，当前为 {ic!r}。")
        pf = cov.get("pagesFetched")
        if pf is not None and (not isinstance(pf, int) or isinstance(pf, bool) or pf < 0):
            errs.append("coverage.pagesFetched 必须是 >= 0 的整数或 null。")
        if "coverageNote" in cov and not isinstance(cov["coverageNote"], str):
            errs.append("coverage.coverageNote 必须是字符串。")
        # 一致性：声明条数应与 orders 实际条数吻合
        orders_for_check = data.get("orders")
        if isinstance(n, int) and isinstance(orders_for_check, list):
            if n != len(orders_for_check):
                errs.append(
                    f"coverage.orderCountFetched 声明为 {n}，但 orders 实际有 "
                    f"{len(orders_for_check)} 条，二者必须一致。"
                )
        # 一致性：开始时间不得晚于结束时间
        s_dt, e_dt = _parse_iso(cov.get("ordersStart")), _parse_iso(cov.get("ordersEnd"))
        if s_dt and e_dt and s_dt > e_dt:
            errs.append("coverage.ordersStart 晚于 ordersEnd，时间区间不成立。")

    # ---- account
    acc = data.get("account")
    if not isinstance(acc, dict):
        errs.append("缺少 account 段。")
    else:
        st = acc.get("status")
        if st is not None and st not in VALID_ACCT_STATUS:
            errs.append(f"account.status 取值必须是 {VALID_ACCT_STATUS} 之一，当前为 {st!r}。")
        for k in ("available", "accumulated", "frozen", "expiringSoon"):
            if k in acc and not _is_num_or_none(acc[k]):
                errs.append(f"account.{k} 必须是数字或 null（未知请用 null，不要用 0）。")
        if "note" in acc and not isinstance(acc["note"], str):
            errs.append("account.note 必须是字符串。")

    # ---- coupons
    cp = data.get("coupons")
    if cp is not None and not isinstance(cp, dict):
        errs.append("coupons 必须是对象。")
    elif isinstance(cp, dict):
        st = cp.get("status")
        if st is not None and st not in VALID_ACCT_STATUS:
            errs.append(f"coupons.status 取值必须是 {VALID_ACCT_STATUS} 之一，当前为 {st!r}。")
        tc = cp.get("totalCount")
        if tc is not None and (not isinstance(tc, int) or isinstance(tc, bool) or tc < 0):
            errs.append("coupons.totalCount 必须是 >= 0 的整数或 null。")
        bc = cp.get("byCategory")
        if bc is not None:
            if not isinstance(bc, dict):
                errs.append("coupons.byCategory 必须是对象或 null。")
            else:
                for k, v in bc.items():
                    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                        errs.append(f"coupons.byCategory[{k!r}] 必须是 >= 0 的整数。")

    # ---- orders（逐个成员深度校验）
    orders = data.get("orders")
    if orders is not None:
        if not isinstance(orders, list):
            errs.append("orders 必须是数组。")
        else:
            for i, o in enumerate(orders):
                tag = f"orders[{i}]"
                if o is None:
                    errs.append(f"{tag} 是 null——订单记录必须是对象；空记录请直接从数组中移除。")
                    continue
                if not isinstance(o, dict):
                    errs.append(f"{tag} 必须是对象，当前为 {type(o).__name__}。")
                    continue
                if "id" in o and not isinstance(o["id"], str):
                    errs.append(f"{tag}.id 必须是字符串。")
                if "createdAt" in o and o["createdAt"] is not None:
                    if _parse_iso(o["createdAt"]) is None:
                        errs.append(f"{tag}.createdAt 不是可解析的 ISO 时间：{str(o['createdAt'])[:40]!r}")
                st = o.get("status")
                if st is None:
                    errs.append(f"{tag} 缺少 status 字段。")
                elif st not in VALID_STATUS:
                    errs.append(f"{tag}.status 取值必须是 {VALID_STATUS} 之一，当前为 {st!r}。")
                if "statusRaw" in o and not isinstance(o["statusRaw"], str):
                    errs.append(f"{tag}.statusRaw 必须是字符串（保留官方原文，无则用空串）。")
                if "isCompleted" in o and not isinstance(o["isCompleted"], bool):
                    errs.append(f"{tag}.isCompleted 必须是布尔值。")
                # 一致性：isCompleted 必须与 status 匹配
                if st in VALID_STATUS and isinstance(o.get("isCompleted"), bool):
                    want = (st == "completed")
                    if o["isCompleted"] != want:
                        errs.append(
                            f"{tag} 自相矛盾：status={st!r} 但 isCompleted={o['isCompleted']}。"
                            f"（status='completed' 时 isCompleted 必须为 true，其余必须为 false）"
                        )
                if "amount" in o and not _is_num_or_none(o["amount"]):
                    errs.append(f"{tag}.amount 必须是数字或 null（未知请用 null，不要用 0）。")
                for k in ("currency", "channel", "storeId", "storeName"):
                    if k in o and o[k] is not None and not isinstance(o[k], str):
                        errs.append(f"{tag}.{k} 必须是字符串或 null。")
                items = o.get("items")
                if items is not None:
                    if not isinstance(items, list):
                        errs.append(f"{tag}.items 必须是数组或 null。")
                    else:
                        for j, it in enumerate(items):
                            if not isinstance(it, dict):
                                errs.append(f"{tag}.items[{j}] 必须是对象。")
                                continue
                            if not isinstance(it.get("name"), str):
                                errs.append(f"{tag}.items[{j}].name 必须是字符串。")
                            q = it.get("quantity")
                            if q is not None and (not isinstance(q, int) or isinstance(q, bool) or q < 0):
                                errs.append(f"{tag}.items[{j}].quantity 必须是 >= 0 的整数或 null。")

    # ---- stores（逐个成员）
    stores = data.get("stores")
    if stores is not None:
        if not isinstance(stores, list):
            errs.append("stores 必须是数组。")
        else:
            for i, s in enumerate(stores):
                tag = f"stores[{i}]"
                if not isinstance(s, dict):
                    errs.append(f"{tag} 必须是对象。")
                    continue
                if not isinstance(s.get("storeId"), str):
                    errs.append(f"{tag}.storeId 必须是字符串。")
                if "storeName" in s and s["storeName"] is not None and not isinstance(s["storeName"], str):
                    errs.append(f"{tag}.storeName 必须是字符串或 null。")
                oc = s.get("orderCount")
                if not isinstance(oc, int) or isinstance(oc, bool) or oc < 1:
                    errs.append(f"{tag}.orderCount 必须是 >= 1 的整数。")
                if "source" in s and s["source"] != "order-list":
                    errs.append(f'{tag}.source 必须是 "order-list"（门店只能来自订单记录）。')

    # ---- unknowns（逐个成员）
    unknowns = data.get("unknowns")
    if unknowns is not None:
        if not isinstance(unknowns, list):
            errs.append("unknowns 必须是数组。")
        else:
            for i, u in enumerate(unknowns):
                if not isinstance(u, dict):
                    errs.append(f"unknowns[{i}] 必须是对象。")
                    continue
                if not isinstance(u.get("field"), str):
                    errs.append(f"unknowns[{i}].field 必须是字符串。")
                if not isinstance(u.get("reason"), str):
                    errs.append(f"unknowns[{i}].reason 必须是字符串。")

    # ---- warnings（逐个成员）
    warnings = data.get("warnings")
    if warnings is not None:
        if not isinstance(warnings, list):
            errs.append("warnings 必须是数组。")
        else:
            for i, w in enumerate(warnings):
                if not isinstance(w, str):
                    errs.append(f"warnings[{i}] 必须是字符串。")

    return errs


# ---------------------------------------------------------------- rendering

def section(title, cover, target, inner):
    parts = ['<section class="card">']
    parts.append(f'<h2>{esc(title)}</h2>')
    parts.append(inner)
    if cover:
        parts.append(f'<div class="cover"><b>覆盖范围：</b>{esc(cover)}</div>')
    if target:
        parts.append(f'<div class="notarget">{esc(target)}</div>')
    parts.append('</section>')
    return "".join(parts)


def cells(pairs):
    out = ['<div class="grid">']
    for k, v in pairs:
        out.append(f'<div class="cell"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>')
    out.append('</div>')
    return "".join(out)


def row(left, right, tag=None):
    t = f' <span class="tag {STATUS_CLASS[tag]}">{STATUS_ZH[tag]}</span>' if tag else ""
    return (
        f'<div class="row"><div class="l">{esc(left)}{t}</div>'
        f'<div class="r">{esc(right)}</div></div>'
    )


def unknown_block(unknowns):
    if not unknowns:
        return ""
    out = ['<div class="known-unknown"><div>以下项目本次未能确认：</div><ul>']
    for u in unknowns:
        if not isinstance(u, dict):
            continue
        f_ = u.get("field") or "未命名字段"
        r_ = u.get("reason") or "原因未知"
        i_ = u.get("impact") or "未说明"
        out.append(f"<li>{esc(f_)} —— {esc(r_)}（影响：{esc(i_)}）</li>")
    out.append("</ul></div>")
    return "".join(out)


def details_block(summary, inner):
    """工程说明折叠块：普通页面不展开，需要时再展开查看。"""
    if not inner:
        return ""
    return ('<details class="tech"><summary>' + esc(summary) + '</summary>'
            '<div class="techin">' + inner + '</div></details>')


def render_body(data):
    cov = data.get("coverage") or {}
    cover = cover_text(cov, include_note=False)
    acc = data.get("account") or {}
    cp = data.get("coupons") or {}
    orders = data.get("orders") or []
    stores = data.get("stores") or []
    unks = data.get("unknowns") or []
    warns = data.get("warnings") or []
    src = data.get("source") or {}

    blocks = []
    tech = []          # 折叠区的工程说明内容

    # ---------------- 横幅 ----------------
    blocks.append('<div class="banner demo">示例数据 · 非真实账户</div>' if data.get("_sample")
                  else '<div class="banner">账户快照 · 本次查询结果</div>')
    if warns:
        blocks.append('<div class="banner">部分数据本次未能取得，详情可查看下方说明。</div>')
        tech.append('<div class="techh">查询说明</div>')
        tech.extend('<div class="technote">' + esc(w) + '</div>' for w in warns)

    blocks.append('<div class="cards">')

    # ---------------- 1 当前积分（普通页面突出） ----------------
    acc_status = acc.get("status")
    if acc_status == "unavailable":
        inner = '<div class="empty">积分数据本次不可得。</div>'
    elif acc_status == "unknown":
        # 字段含义未能确认 —— 显示「未知」，不显示数字，更不得显示 0
        inner = ('<div class="big unknownv">未知</div>'
                 '<div class="cover">可用积分（字段含义未能确认）</div>')
    else:
        inner = ('<div class="big">' + esc(num(acc.get("available"))) + '</div>'
                 '<div class="cover">可用积分</div>'
                 + cells([("累计积分", num(acc.get("accumulated"))),
                          ("冻结积分", num(acc.get("frozen"))),
                          ("即将过期", num(acc.get("expiringSoon")))]))
    blocks.append(section("当前积分", cover, "账户级数据，与订单区间无关。", inner))
    if acc.get("note"):
        tech.append('<div class="technote">积分字段说明：' + esc(acc["note"]) + '</div>')

    # ---------------- 2 券摘要（普通页面突出） ----------------
    if cp.get("status") == "unavailable":
        inner = '<div class="empty">券数据本次不可得。</div>'
    else:
        inner = ('<div class="big">' + esc(num(cp.get("totalCount"))) + '</div>'
                 '<div class="cover">当前可用券总数</div>')
        cats = cp.get("byCategory")
        if isinstance(cats, dict) and cats:
            inner += cells([(k, num(v)) for k, v in cats.items()])
    blocks.append(section("券摘要", cover, "仅统计数量与类别，不列出券码。", inner))
    if cp.get("note"):
        tech.append('<div class="technote">券字段说明：' + esc(cp["note"]) + '</div>')

    # ---------------- 3 订单 ----------------
    completed = [o for o in orders if norm_status(o.get("status")) == "completed" and o.get("isCompleted") is True]
    cancelled = [o for o in orders if norm_status(o.get("status")) == "cancelled"]
    refunded = [o for o in orders if norm_status(o.get("status")) == "refunded"]
    unk_orders = [o for o in orders if norm_status(o.get("status")) == "unknown"]
    conflicted = [
        o for o in orders
        if (norm_status(o.get("status")) == "completed" and o.get("isCompleted") is not True)
        or (norm_status(o.get("status")) != "completed" and o.get("isCompleted") is True)
    ]

    if not orders:
        # 未取回订单：把空概览/空状态/空门店三张卡合并为一条简洁提示
        inner = ('<div class="empty">本次未取回任何订单记录。</div>'
                 '<div class="ordernote">因此本页不展示订单明细、状态分类与门店足迹 —— '
                 '没有取回的数据，我们不做任何猜测。</div>')
        blocks.append(section("订单记录", cover,
                              "订单数据不可得时，本项目不生成任何替代性内容。", inner))
    else:
        # 3a 订单概览
        inner = cells([
            ("取回记录", f"{len(orders)} 条"),
            ("已完成", f"{len(completed)} 条"),
            ("已取消", f"{len(cancelled)} 条"),
            ("已退款", f"{len(refunded)} 条"),
            ("状态未知", f"{len(unk_orders)} 条"),
        ])
        if cov.get("isComplete") in ("partial", "unknown"):
            inner += ('<div class="banner">'
                      + ("注意：本次仅取回部分记录，以上计数不代表完整历史。"
                         if cov.get("isComplete") == "partial"
                         else "注意：无法确认是否已取全记录，以上计数谨慎参考。")
                      + "</div>")
        if conflicted:
            inner += f'<div class="banner">有 {len(conflicted)} 条记录的 status 与 isCompleted 不一致，均未计入已完成。</div>'
        blocks.append(section("订单概览", cover, "已取消 / 已退款独立统计，不计入已完成订单数。", inner))

        # 3b 明细
        shown = [o for o in orders if norm_status(o.get("status")) != "unknown"]
        # 冲突记录（status 与 isCompleted 不一致）：不得在明细里给出确定性状态标签，
        # 否则会出现「文字说已完成、标记说不计入」的自相矛盾展示。
        conflict_ids = {id(o) for o in conflicted}
        if not shown:
            inner = '<div class="empty">本次取回的记录状态均无法确认。</div>'
        else:
            inner = "".join(
                row(
                    fmt_time(o.get("createdAt"))
                    + (f' · {o["storeName"]}' if isinstance(o.get("storeName"), str) and o.get("storeName") else "")
                    + (f' · {o["channel"]}' if isinstance(o.get("channel"), str) and o.get("channel") else "")
                    + (" · 标记与状态不一致" if id(o) in conflict_ids else ""),
                    str(o.get("id") or "（无标识）"),
                    "unknown" if id(o) in conflict_ids else norm_status(o.get("status")),
                )
                for o in shown[:50]
            )
            if len(shown) > 50:
                inner += f'<div class="cover">（共 {len(shown)} 条，此处仅展示前 50 条）</div>'
            if conflict_ids:
                inner += ('<div class="cover">标注「状态未知」的记录，其状态字段与计入标记互相矛盾，'
                          '为避免误导，本项目不对其给出确定性结论。</div>')
        blocks.append(section("订单记录（已明确状态）", cover, "仅展示状态可确定的记录；状态未知的单列在下一张卡。", inner))

        # 3c 未知状态订单
        if not unk_orders:
            inner = '<div class="empty">本次没有状态未知的记录。</div>'
        else:
            inner = "".join(
                row(
                    fmt_time(o.get("createdAt")) + " · 原始状态：" + (str(o["statusRaw"]) if o.get("statusRaw") else "（空）"),
                    str(o.get("id") or "（无标识）"),
                    "unknown",
                )
                for o in unk_orders
            )
            inner += '<div class="cover">这些记录未计入任何统计口径。</div>'
        blocks.append(section("状态未知的记录", cover, "既不当作完成，也不当作取消。", inner))

        # 3d 门店
        if not stores:
            inner = '<div class="empty">本次订单记录中未包含门店信息，故不生成门店足迹。</div>'
        else:
            ordered = sorted(stores, key=lambda s: -(s.get("orderCount") or 0))
            inner = "".join(
                row(
                    (s.get("storeName") if isinstance(s.get("storeName"), str) and s.get("storeName")
                     else (str(s.get("storeId")) if s.get("storeId") else "未命名门店")),
                    f"{num(s.get('orderCount'))} 次",
                )
                for s in ordered
            )
            inner += '<div class="cover">以上门店来自 order-list 返回记录，非附近推荐。</div>'
        blocks.append(section("门店记录", cover,
                              "门店仅来源于订单记录。绝不使用「附近门店」代替历史足迹。", inner))

    blocks.append("</div>")   # /.cards

    # ---------------- 查看数据说明（折叠：工程信息） ----------------
    s_d, e_d = fmt_date(cov.get("ordersStart")), fmt_date(cov.get("ordersEnd"))
    scope = f"{s_d} 至 {e_d}" if (s_d and e_d) else ("时间范围无法确定" if cov.get("orderCountFetched") else "无订单记录")
    integrity = {"complete": "已确认取全", "partial": "仅取回部分（分页受限）"}.get(
        cov.get("isComplete"), "无法判断是否取全")

    tech.append('<div class="techh">数据范围</div>')
    tech.append(cells([
        ("时间范围", scope),
        ("取回条数", f"{num(cov.get('orderCountFetched'))} 条"),
        ("完整性", integrity),
        ("已取页数", UNKNOWN if cov.get("pagesFetched") is None else str(cov.get("pagesFetched"))),
    ]))
    if cov.get("coverageNote"):
        tech.append('<div class="technote">' + esc(cov["coverageNote"]) + '</div>')

    tech.append('<div class="techh">本次调用的只读工具</div>')
    if isinstance(src.get("tools"), list) and src["tools"]:
        tech.append('<div class="technote">成功调用：' + esc("、".join(str(t) for t in src["tools"])) + '</div>')
    else:
        tech.append('<div class="technote">成功调用：' + UNKNOWN + '</div>')
    if isinstance(src.get("toolsFailed"), list) and src["toolsFailed"]:
        tech.append('<div class="known-unknown"><div>未能取数的工具：</div><ul>')
        for tf in src["toolsFailed"]:
            if isinstance(tf, dict):
                tech.append('<li>' + esc(tf.get("tool") or "未知工具") + ' —— '
                            + esc(tf.get("reason") or "原因未知") + '</li>')
        tech.append("</ul></div>")
    if isinstance(src.get("writeToolsInvoked"), list) and src["writeToolsInvoked"]:
        tech.append('<div class="banner err">检测到写工具调用记录，本页不应渲染。</div>')
    else:
        tech.append('<div class="technote">写工具调用记录：无（本作品全只读）。</div>')

    if unks:
        tech.append('<div class="techh">本次无法确认的项</div>')
        tech.append(unknown_block(unks))

    tech.append('<div class="techh">数据格式</div>')
    tech.append('<div class="technote">本项目自定义归一化数据模型 v'
                + esc(str(data.get("schemaVersion") or UNKNOWN))
                + '（schema 文件：references/normalized.schema.json）。'
                + '未取回的字段一律显示为「未知」，不以 0 代替。</div>')
    if data.get("generatedAt"):
        tech.append('<div class="technote">归一化数据生成时间：' + esc(str(data["generatedAt"])) + '</div>')

    blocks.append(details_block("查看数据说明", "".join(tech)))

    return "".join(blocks)

CSS = """
:root{--bg:#f5f2ec;--card:#fff;--ink:#1b1b1b;--ink2:#5b5b5b;--ink3:#8a8a8a;--line:#e4ded4;
--accent:#c8102e;--accent-soft:#fdeef0;--warn:#8a6d1f;--warn-soft:#fdf6e3;--unknown:#6b6b6b;--unknown-soft:#f0efed}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);padding:28px 16px 64px;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
.wrap{max-width:720px;margin:0 auto}
h1{font-size:24px;margin:0;letter-spacing:-.3px}
.brand small{color:var(--ink3);font-size:12px;margin-left:10px}
.sub{color:var(--ink2);font-size:13px;margin:8px 0 18px}
.banner{border-radius:12px;padding:11px 14px;font-size:12.5px;margin:12px 0;
background:var(--warn-soft);color:var(--warn);border:1px solid #f0e3bd}
.banner.demo{background:var(--accent-soft);color:var(--accent);border-color:#f6d3d8;font-weight:600}
.banner.err{background:#fdeeee;color:#a32020;border-color:#f3cccc}
.cards{display:flex;flex-direction:column;gap:14px}
.card{background:var(--card);border-radius:16px;padding:20px 20px 14px;
box-shadow:0 1px 2px rgba(0,0,0,.04),0 6px 20px rgba(0,0,0,.05);border:1px solid rgba(0,0,0,.03);break-inside:avoid}
.card h2{font-size:14px;margin:0 0 12px;color:var(--ink2);font-weight:600;display:flex;align-items:center;gap:8px}
.card h2::before{content:"";width:3px;height:14px;border-radius:2px;background:var(--accent)}
.big{font-size:30px;font-weight:700;letter-spacing:-.5px;line-height:1.2}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:10px;margin-top:4px}
.cell{background:#faf8f5;border-radius:10px;padding:10px 12px}
.cell .k{font-size:11px;color:var(--ink3)}
.cell .v{font-size:17px;font-weight:600;margin-top:2px}
.row{display:flex;justify-content:space-between;gap:12px;align-items:baseline;
padding:9px 0;border-bottom:1px solid #f2efe9;font-size:13.5px}
.row:last-child{border-bottom:none}
.row .l{color:var(--ink2);flex:1;min-width:0;overflow-wrap:anywhere}
.row .r{color:var(--ink);font-weight:600;white-space:nowrap}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:999px;
background:var(--unknown-soft);color:var(--unknown);font-weight:600}
.tag.ok{background:#eaf6ee;color:#2b6b41}.tag.cancel{background:#fdeeee;color:#a32020}
.tag.refund{background:#eef2fb;color:#33518c}.tag.unknown{background:var(--unknown-soft);color:var(--unknown)}
.known-unknown{margin-top:12px;padding:10px 12px;border-radius:10px;background:var(--unknown-soft);
font-size:12px;color:var(--ink2)}
.known-unknown ul{margin:6px 0 0;padding-left:18px}
.cover{margin-top:14px;padding-top:11px;border-top:1px dashed var(--line);font-size:11.5px;color:var(--ink3)}
.cover b{color:var(--ink2)}
.notarget{margin-top:10px;font-size:11.5px;color:var(--ink3);font-style:italic}
.empty{text-align:center;padding:32px 20px;color:var(--ink3);font-size:14px}
footer{margin-top:26px;font-size:11.5px;color:var(--ink3)}
.ordernote{margin-top:10px;font-size:12.5px;color:var(--ink2);line-height:1.7}
.big.unknownv{color:var(--ink3);font-size:26px}
details.tech{margin-top:16px;background:var(--card);border-radius:14px;border:1px solid var(--line);box-shadow:0 1px 2px rgba(0,0,0,.03);break-inside:avoid}
details.tech>summary{cursor:pointer;padding:14px 18px;font-size:13px;color:var(--ink2);font-weight:600;list-style:none;display:flex;align-items:center;gap:8px}
details.tech>summary::-webkit-details-marker{display:none}
details.tech>summary::before{content:"▸";color:var(--accent);font-size:12px;display:inline-block;transition:transform .15s}
details.tech[open]>summary::before{transform:rotate(90deg)}
.techin{padding:0 18px 16px}
.techh{margin:14px 0 6px;font-size:12px;font-weight:700;color:var(--ink)}
.technote{font-size:11.5px;color:var(--ink3);line-height:1.65;margin-top:4px;overflow-wrap:anywhere}
.techin .grid{margin-top:2px}
@media print{body{background:#fff;padding:0}.card{box-shadow:none;border:1px solid var(--line)}}
@media (max-width:480px){body{padding:20px 12px 48px}h1{font-size:20px}
.grid{grid-template-columns:repeat(2,1fr)}.big{font-size:26px}}
"""


def build_html(data, source_path):
    errs = validate(data)
    gen = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    if errs:
        body = ('<div class="banner err"><div>无法渲染该数据：</div><ul>'
                + "".join(f"<li>{esc(e)}</li>" for e in errs) + "</ul></div>")
    else:
        body = render_body(data)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>麦门回忆卡 · 静态卡片页</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="brand"><h1 style="display:inline">麦门回忆卡</h1><small>mcd-memory-card</small></div>
  <p class="sub">积分、优惠券与近期记录，一眼看清。生成于 {esc(gen)}。</p>
  {body}
  <footer>
    <div>本页为静态文件，不含脚本、不联网、不上传、不存储任何令牌。</div>
    <div>数据口径：订单 ≠ 摄入；消费记录 ≠ 完整历史。卡片仅依据实际取回的记录陈述。</div>
    <div>麦当劳程序员创意开发大赛参赛作品，非麦当劳官方产品。</div>
  </footer>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="把归一化 JSON 渲染成静态 HTML 卡片页")
    ap.add_argument("input", nargs="?", help="归一化 JSON 路径；省略则从 stdin 读取")
    ap.add_argument("-o", "--output", help="输出 HTML 路径；省略则打印到 stdout")
    args = ap.parse_args()

    raw = ""
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[错误] JSON 解析失败：{e}\n")
        return 2

    errs = validate(data)
    if errs:
        sys.stderr.write("[警告] 数据校验未通过，仍将输出错误页：\n")
        for e in errs:
            sys.stderr.write(f"  - {e}\n")

    out = build_html(data, args.input)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
        sys.stderr.write(f"[完成] 已写入 {os.path.abspath(args.output)}\n")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
