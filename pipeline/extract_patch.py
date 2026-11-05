#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
王者教研室 · 公告结构化抽取（RAG 管线第 2 步）

输入：pipeline/out/articles/<tid>.json（fetch_article.mjs 的产物）
输出：pipeline/out/extracted/<tid>.json
      - sections：按「英雄调整 / 装备调整 / 机制调整 / 问题修复 …」分节
      - changes：启发式抽取的「某英雄/装备 某属性 from → to」改动
      - llm：可选，若配置了 LLM_API_KEY 则用大模型做结构化抽取（JSON mode）

说明：
- 默认不依赖任何第三方库；无 LLM Key 时用规则抽取，足以覆盖官方公告的数值行格式。
- 有 Key 时用 OpenAI 兼容接口（DeepSeek/Kimi/Qwen 均可），返回严格 JSON；失败自动回退规则结果。

用法：
    python pipeline/extract_patch.py 812092
    python pipeline/extract_patch.py 812092 --no-llm
"""
import glob
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "pipeline", "out")
LOCAL_DATA = os.path.join(BASE, "next", "src", "data", "data.json")

SECTION_NAMES = [
    "英雄调整", "装备调整", "机制调整", "共鸣调整", "战场机制调整", "问题修复",
    "夺宝更新", "版本活动", "活动更新", "商城更新", "系统更新", "其他更新",
    "新增英雄", "英雄重做", "皮肤优化", "体验优化", "平衡性调整",
]
CHANGE_MARK = "→"


def load_latest_snapshot():
    dirs = sorted(glob.glob(os.path.join(OUT, "snapshot-*")))
    heroes = {}
    items = {}
    if dirs:
        snap = dirs[-1]
        hp = os.path.join(snap, "herolist.json")
        ip = os.path.join(snap, "items.json")
        if os.path.exists(hp):
            with open(hp, encoding="utf-8") as f:
                heroes = {h["cname"]: h for h in json.load(f) if h.get("cname")}
        if os.path.exists(ip):
            with open(ip, encoding="utf-8") as f:
                items = {i["item_name"]: i for i in json.load(f) if i.get("item_name")}
    if not heroes and os.path.exists(LOCAL_DATA):
        with open(LOCAL_DATA, encoding="utf-8") as f:
            data = json.load(f)
        heroes = {h["name"]: h for h in data.get("heroes", [])}
    return heroes, items


def split_sections(text):
    lines = [ln.strip() for ln in text.splitlines()]
    sections = {}
    current = None
    for ln in lines:
        if not ln:
            continue
        if ln in SECTION_NAMES:
            current = ln
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(ln)
    return sections


def extract_hero_changes(section_lines, hero_names):
    """在「英雄调整」节里抽取：英雄名 → 其后的改动行（含 → 或 数值）"""
    changes = []
    current_hero = None
    for ln in section_lines:
        name = None
        for h in hero_names:
            if ln == h or ln.startswith(h + "：") or ln.startswith(h + "（") or ln.startswith(h + ":"):
                name = h
                break
        if name:
            current_hero = name
            rest = ln[len(name):].lstrip("：（(: ")
            if rest:
                changes.append({"type": "hero", "name": name, "text": rest,
                                "from": None, "to": None})
            continue
        if current_hero is None:
            continue
        if CHANGE_MARK in ln or re.search(r"[0-9]", ln):
            rec = {"type": "hero", "name": current_hero, "text": ln, "from": None, "to": None}
            if CHANGE_MARK in ln:
                a, b = ln.split(CHANGE_MARK, 1)
                # 去掉技能名/属性名前缀，取最后一段数值
                rec["from"] = a.strip()
                rec["to"] = b.strip()
            changes.append(rec)
    return changes


def extract_simple_changes(section_lines, kind, whitelist):
    changes = []
    for ln in section_lines:
        if CHANGE_MARK not in ln:
            continue
        hit = None
        for name in whitelist:
            if name in ln:
                hit = name
                break
        a, b = ln.split(CHANGE_MARK, 1)
        changes.append({"type": kind, "name": hit, "text": ln,
                        "from": a.strip(), "to": b.strip()})
    return changes


def optional_llm(article, heuristic):
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    base = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "deepseek-chat")
    prompt = (
        "你是王者荣耀数据整理助手。下面是官方版本更新公告全文。"
        "只提取公告里明确写出的改动（英雄/装备/机制），不要推测；"
        "每条改动给出 evidence（原文一句话）。"
        "输出严格 JSON：{\"changes\":[{\"type\":\"hero|item|mechanic\",\"name\":\"\","
        "\"field\":\"\",\"from\":\"\",\"to\":\"\",\"direction\":\"buff|nerf|adjust\","
        "\"impact\":\"\",\"evidence\":\"\"}]}。没有明确数值也保留定性改动。\n\n"
        "公告标题：" + article.get("title", "") + "\n公告全文：\n" + article.get("text", "")[:12000]
    )
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要 markdown 代码块。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = __import__("urllib.request").request.Request(
        base + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with __import__("urllib.request").request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        result["_model"] = model
        return result
    except Exception as exc:  # noqa: BLE001
        print("  LLM 抽取失败，回退规则结果:", exc)
        return None


def validate(changes, hero_names, item_names, article_text):
    warnings = []
    for ch in changes:
        name = ch.get("name")
        if ch.get("type") == "hero" and name and name not in hero_names:
            warnings.append("英雄不在官方列表: " + name)
        if ch.get("type") == "item" and name and name not in item_names:
            warnings.append("装备不在官方列表: " + name)
        evidence = ch.get("text") or ch.get("evidence")
        if evidence and evidence[:20] not in article_text:
            warnings.append("证据文本无法在公告中检索到: " + evidence[:40])
    return warnings


def main():
    tid = None
    no_llm = "--no-llm" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            tid = a
    if not tid:
        print("usage: python pipeline/extract_patch.py <tid> [--no-llm]")
        sys.exit(1)

    article_path = os.path.join(OUT, "articles", tid + ".json")
    if not os.path.exists(article_path):
        print("缺少公告正文，请先运行: node pipeline/fetch_article.mjs", tid)
        sys.exit(2)
    with open(article_path, encoding="utf-8") as f:
        article = json.load(f)

    heroes, items = load_latest_snapshot()
    text = article.get("text", "")
    sections = split_sections(text)

    hero_names = set(heroes.keys())
    item_names = set(items.keys())
    changes = []
    if "英雄调整" in sections:
        changes += extract_hero_changes(sections["英雄调整"], hero_names)
    if "装备调整" in sections:
        changes += extract_simple_changes(sections["装备调整"], "item", item_names)
    if "机制调整" in sections:
        changes += extract_simple_changes(sections["机制调整"], "mechanic", [])
    if "共鸣调整" in sections:
        changes += extract_simple_changes(sections["共鸣调整"], "mechanic", [])

    llm = None if no_llm else optional_llm(article, changes)
    warnings = validate(changes, hero_names, item_names, text)

    result = {
        "patchId": tid,
        "title": article.get("title"),
        "sourceUrl": article.get("sourceUrl"),
        "fetchedAt": article.get("fetchedAt"),
        "sections": {k: len(v) for k, v in sections.items()},
        "changes": changes,
        "heroNames": sorted({c["name"] for c in changes if c.get("type") == "hero" and c.get("name")}),
        "itemNames": sorted({c["name"] for c in changes if c.get("type") == "item" and c.get("name")}),
        "warnings": warnings,
        "llm": llm,
        "heuristicChangeCount": len(changes),
    }
    os.makedirs(os.path.join(OUT, "extracted"), exist_ok=True)
    out_file = os.path.join(OUT, "extracted", tid + ".json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("公告:", result["title"])
    print("分节:", result["sections"])
    print("规则抽取改动:", len(changes), "| 涉及英雄:", len(result["heroNames"]))
    print("英雄:", "、".join(result["heroNames"][:20]))
    if warnings:
        print("校验警告:", len(warnings))
        for w in warnings[:8]:
            print("  -", w)
    if llm:
        print("LLM 抽取改动:", len(llm.get("changes", [])))
    print("产物:", out_file)


if __name__ == "__main__":
    main()
