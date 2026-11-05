#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
王者教研室 · 官方数据源采集与对比（RAG 管线第 1 步）

用法：
    python pipeline/fetch_sources.py

输出：
    pipeline/out/snapshot-YYYY-MM-DD/herolist.json
    pipeline/out/snapshot-YYYY-MM-DD/items.json
    pipeline/out/snapshot-YYYY-MM-DD/announcements.json
    pipeline/out/source_report.json      # 与当前 App 数据快照的差异
    pipeline/out/source_report.txt       # 人类可读摘要

只用 Python 标准库，无第三方依赖。首次运行约 5~10 秒。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # wangzhe-apk/
OUT = os.path.join(BASE, "pipeline", "out")
LOCAL_DATA = os.path.join(BASE, "next", "src", "data", "data.json")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://pvp.qq.com/",
}

HERO_LIST = "https://pvp.qq.com/web201605/js/herolist.json"
ITEM_LIST = "https://pvp.qq.com/web201605/js/item.json"
NEWS_INDEX = "https://pvp.qq.com/web201706/newsindex.shtml"

# 官网公告列表接口（王者荣耀 serviceId=18；token 来自官网 newsindex.js）
CMC_CROSS = "https://apps.game.qq.com/cmc/cross"
CMC_TOKEN = "234ce0aef3020cb83887883877b64869"


def fetch_bytes(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json(url):
    return json.loads(fetch_bytes(url).decode("utf-8", "replace"))


def fetch_text(url):
    raw = fetch_bytes(url)
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")


def fetch_announcements_via_cmc(chanid=1762, limit=30):
    """官方公告列表接口（签名规则见官网 newsindex.js）。

    chanid=1762 是官网「公告」频道（页面 data-channelid=1762），
    比静态 page HTML 新（page 可能被 CDN 缓存到旧版本，导致漏掉新公告）。
    """
    ts = int(time.time())
    sign = __import__("hashlib").md5(
        (CMC_TOKEN + "web_pc" + "18" + str(ts)).encode("utf-8")
    ).hexdigest()
    params = {
        "serviceId": "18", "filter": "channel", "sortby": "sIdxTime",
        "source": "web_pc", "limit": str(limit), "logic": "or",
        "typeids": "1,2", "chanid": str(chanid), "start": "0",
        "withtop": "yes", "exclusiveChannel": "4",
        "exclusiveChannelSign": sign, "time": str(ts),
    }
    url = CMC_CROSS + "?" + "&".join("%s=%s" % (k, v) for k, v in params.items())
    data = fetch_json(url)
    items = data.get("data", {}).get("items", []) or []
    result = []
    for it in items:
        result.append({
            "tid": it.get("iId"),
            "title": it.get("sTitle"),
            "publishedAt": it.get("sIdxTime") or it.get("sCreated") or it.get("iTime"),
            "url": "https://pvp.qq.com/web201706/newsdetail.shtml?G_Biz=18&tid=%s" % it.get("iId"),
        })
    return result


def fetch_announcements_via_page():
    """兜底：解析官网新闻列表页的公告链接。"""
    html = fetch_text(NEWS_INDEX)
    links = re.findall(r'<a[^>]+href="([^"]*tid=(\d+)[^"]*)"[^>]*>([^<]{2,80})</a>', html)
    result, seen = [], set()
    for href, tid, title in links:
        if tid in seen:
            continue
        seen.add(tid)
        title = title.strip()
        if not title:
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://pvp.qq.com" + href
        result.append({"tid": tid, "title": title, "url": href})
        if len(result) >= 120:
            break
    return result


def is_patch_announcement(title):
    keys = ("版本更新公告", "停机更新公告", "不停机更新公告", "问题修复版本更新公告")
    return any(k in title for k in keys)


def load_local_data():
    if not os.path.exists(LOCAL_DATA):
        return None
    with open(LOCAL_DATA, encoding="utf-8") as f:
        return json.load(f)


def summarize_hero_diff(official, local):
    off_names = [h.get("cname", "") for h in official]
    loc_names = [h.get("name", "") for h in (local or {}).get("heroes", [])]
    off_set, loc_set = set(off_names), set(loc_names)
    return {
        "official_count": len(off_names),
        "local_count": len(loc_names),
        "official_not_local": sorted(off_set - loc_set),
        "local_not_official": sorted(loc_set - off_set),
    }


def summarize_item_diff(official, local):
    off_names = [i.get("item_name", "") for i in official]
    items = (local or {}).get("items") or []
    if isinstance(items, dict):
        loc_names = list(items.keys())
    elif items and isinstance(items[0], dict):
        loc_names = [i.get("name", "") for i in items]
    else:
        loc_names = list(items)
    off_set, loc_set = set(off_names), set(loc_names)
    return {
        "official_count": len(off_names),
        "local_count": len(loc_names),
        "official_not_local": sorted(off_set - loc_set),
        "local_not_official": sorted(loc_set - off_set),
    }


def main():
    today = date.today().isoformat()
    snapdir = os.path.join(OUT, "snapshot-" + today)
    os.makedirs(snapdir, exist_ok=True)

    print("== 1/4 拉取官方英雄列表 ==")
    heroes = fetch_json(HERO_LIST)
    with open(os.path.join(snapdir, "herolist.json"), "w", encoding="utf-8") as f:
        json.dump(heroes, f, ensure_ascii=False, indent=1)
    print("   heroes:", len(heroes))

    print("== 2/4 拉取官方装备列表 ==")
    items = fetch_json(ITEM_LIST)
    with open(os.path.join(snapdir, "items.json"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    print("   items:", len(items))

    print("== 3/4 拉取官方公告列表 ==")
    announcements = []
    source = ""
    # 优先用官方 CMC 接口（实时），静态页面作为兜底（CDN 可能缓存到旧版本）
    try:
        announcements = fetch_announcements_via_cmc(1762, 30)
        source = "CMC api / chanid=1762（公告）"
        print("   via CMC api:", len(announcements))
    except Exception as exc:  # noqa: BLE001
        print("   CMC api failed:", exc)
    if not announcements:
        try:
            announcements = fetch_announcements_via_page()
            source = "page parse（兜底，可能滞后）"
            print("   via page parse:", len(announcements))
        except Exception as exc:  # noqa: BLE001
            print("   page parse failed:", exc)
    with open(os.path.join(snapdir, "announcements.json"), "w", encoding="utf-8") as f:
        json.dump(announcements, f, ensure_ascii=False, indent=1)
    patches = [a for a in announcements if is_patch_announcement(a["title"])]
    # 优先正式服版本更新公告；同类型按 tid 倒序（tid 随公告时间递增）
    patches.sort(key=lambda x: (0 if ("体验服" not in x["title"]) else 1, -int(x["tid"] or 0)))
    print("   patch announcements:", len(patches), "| source:", source)
    for p in patches[:5]:
        print("     -", p["title"], "| tid=", p["tid"], "|", p.get("publishedAt") or "")

    print("== 4/4 与 App 数据快照对比 ==")
    local = load_local_data()
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "snapshotDir": snapdir,
        "announcementSource": source,
        "heroes": summarize_hero_diff(heroes, local),
        "items": summarize_item_diff(items, local),
        "patches": patches[:5],
    }
    with open(os.path.join(OUT, "source_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = []
    lines.append("官方英雄 %d / 本地 %d" % (report["heroes"]["official_count"], report["heroes"]["local_count"]))
    if report["heroes"]["official_not_local"]:
        lines.append("  官方有、本地无: " + "、".join(report["heroes"]["official_not_local"]))
    if report["heroes"]["local_not_official"]:
        lines.append("  本地有、官方无: " + "、".join(report["heroes"]["local_not_official"]))
    lines.append("官方装备 %d / 本地精简版 %d" % (report["items"]["official_count"], report["items"]["local_count"]))
    lines.append("最近版本公告:")
    for p in patches[:3]:
        lines.append("  - %s (%s)" % (p["title"], p["url"]))
    text = "\n".join(lines)
    with open(os.path.join(OUT, "source_report.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print("\n完成，产物目录:", OUT)


if __name__ == "__main__":
    main()
