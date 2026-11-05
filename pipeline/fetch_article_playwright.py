#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无头浏览器抓取官方公告正文（CI / Playwright 版本）。

与 fetch_article.mjs（本机 Edge + puppeteer-core）等价；
在 GitHub Actions 里用 Playwright 的 chromium 更省事：

    pip install playwright
    playwright install chromium
    python pipeline/fetch_article_playwright.py 812092

输出同 fetch_article.mjs：pipeline/out/articles/<tid>.json
"""
import asyncio
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "pipeline", "out", "articles")


async def fetch(tid):
    from playwright.async_api import async_playwright

    url = "https://pvp.qq.com/web201706/newsdetail.shtml?G_Biz=18&tid=%s" % tid
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 1600})
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2500)
            data = await page.evaluate(
                """() => {
                    const h1 = document.querySelector('.artText h1, .article h1, .news-title, h1');
                    const docTitle = (document.title || '').replace(/-王者荣耀.*$/, '').trim();
                    return {
                        title: docTitle || (h1 ? h1.innerText.trim() : ''),
                        text: document.body.innerText || '',
                        url: location.href
                    };
                }"""
            )
        finally:
            await browser.close()

    text = data["text"]
    start = text.find(data["title"])
    clipped = text[start:] if start >= 0 else text
    out = {
        "tid": str(tid),
        "sourceUrl": url,
        "title": data["title"],
        "fetchedAt": __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds"),
        "text": clipped,
        "chars": len(clipped),
    }
    path = os.path.join(OUT, str(tid) + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"tid": tid, "title": out["title"], "chars": out["chars"], "file": path}, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        print("usage: python pipeline/fetch_article_playwright.py <tid>")
        sys.exit(1)
    asyncio.run(fetch(sys.argv[1]))
