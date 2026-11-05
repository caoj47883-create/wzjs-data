/**
 * 王者教研室 · 官方公告正文抓取（RAG 管线第 1.5 步）
 *
 * 官网公告正文由前端 JS 渲染，直接 HTTP 抓 HTML 拿不到内容；
 * 这里用无头浏览器渲染后提取正文，落盘为 JSON 供后续抽取。
 *
 * 用法：
 *   node pipeline/fetch_article.mjs 812092
 *   node pipeline/fetch_article.mjs 812092 --out pipeline/out/articles
 *
 * 依赖：本仓库 tools/node_modules 下的 puppeteer-core + 本机 Edge/Chrome。
 * 环境变量：
 *   EDGE_PATH  浏览器可执行文件路径（默认 Windows Edge）
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

// 优先用本目录 node_modules；没有则复用仓库 tools/node_modules
const require = createRequire(import.meta.url);
let puppeteer;
try {
  puppeteer = require("puppeteer-core");
} catch {
  puppeteer = require("../tools/node_modules/puppeteer-core");
}

const EDGE_DEFAULT = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const browserPath = process.env.EDGE_PATH || EDGE_DEFAULT;
const tid = process.argv[2];
if (!tid) {
  console.error("usage: node pipeline/fetch_article.mjs <tid> [--out dir]");
  process.exit(1);
}
const outIdx = process.argv.indexOf("--out");
const outDir = outIdx > 0 ? process.argv[outIdx + 1] : "pipeline/out/articles";
fs.mkdirSync(outDir, { recursive: true });

const url = `https://pvp.qq.com/web201706/newsdetail.shtml?G_Biz=18&tid=${tid}`;
const browser = await puppeteer.launch({
  executablePath: browserPath,
  headless: true,
  args: ["--no-first-run", "--disable-gpu", "--hide-scrollbars"],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 1600 });
  await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
  await new Promise((r) => setTimeout(r, 2500));
  const data = await page.evaluate(() => {
    const body = document.body.innerText || "";
    const h1 = document.querySelector(".artText h1, .article h1, .news-title, h1");
    const docTitle = (document.title || "").replace(/-王者荣耀.*$/, "").trim();
    return {
      title: docTitle || (h1 ? h1.innerText.trim() : ""),
      url: location.href,
      text: body,
    };
  });
  // 去掉导航栏、页脚等噪音，从公告标题第一次出现开始截取
  const text = data.text;
  const start = text.indexOf(data.title);
  const clipped = start >= 0 ? text.slice(start) : text;
  const out = {
    tid,
    sourceUrl: url,
    title: data.title,
    fetchedAt: new Date().toISOString(),
    text: clipped,
    chars: clipped.length,
  };
  const file = path.join(outDir, `${tid}.json`);
  fs.writeFileSync(file, JSON.stringify(out, null, 2), "utf8");
  console.log(JSON.stringify({ tid, title: out.title, chars: out.chars, file }, null, 2));
} finally {
  await browser.close();
}
