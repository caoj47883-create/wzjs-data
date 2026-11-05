# 数据管线（RAG 定时更新原型）

这条管线把「官方公告 → 结构化改动 → 发布数据包」串起来，供 App 联网热更新使用。
完整架构说明见 [`../docs/ONLINE_UPDATE_ARCHITECTURE.md`](../docs/ONLINE_UPDATE_ARCHITECTURE.md)。

## 文件

| 文件 | 作用 |
| --- | --- |
| `fetch_sources.py` | 拉官方英雄/装备 JSON、公告列表；与 App 当前数据快照对比 |
| `fetch_article.mjs` | 无头浏览器渲染公告正文，落盘 `out/articles/<tid>.json` |
| `extract_patch.py` | 把公告拆节，规则抽取「英雄/装备/机制 from→to」改动；有 LLM Key 时用大模型增强 |
| `publish_release.py` | 生成 App 可拉取的发布目录：`manifest.json` + `releases/<ver>/data.json`（sha256/可选 RSA 签名） |
| `out/` | 运行产物（快照、正文、抽取结果、发布包），可整个删掉重跑 |

## 快速开始（Windows）

```powershell
cd D:\图吧工具箱\wangzhe-apk

# 1) 官方数据源 + 公告列表
python pipeline/fetch_sources.py

# 2) 抓某条公告正文（依赖 tools/node_modules 里的 puppeteer-core）
node pipeline/fetch_article.mjs 812092

# 3) 结构化抽取（无 LLM Key 也能跑规则抽取）
python pipeline/extract_patch.py 812092

# 4) 打包发布（MVP：只校验 sha256）
python pipeline/publish_release.py --version 2026.11.05.1 `
  --data next/src/data/data.json `
  --patches pipeline/out/extracted/812092.json `
  --patch-id 812092 --patch-title "11月5日版本更新公告" `
  --notes "11-05 版本：敖隐/艾琳等调整"
```

产物：

```
pipeline/out/
├── snapshot-2026-11-05/        # 官方原始数据快照
├── source_report.json/.txt     # 与 App 数据的差异
├── articles/812092.json        # 公告正文
├── extracted/812092.json       # 结构化改动（sections/changes/warnings）
└── publish/
    ├── manifest.json           # App 拉取入口
    ├── latest.json
    └── releases/2026.11.05.1/
        ├── data.json
        ├── patches.json
        └── release.json
```

## 接大模型（可选，增强抽取质量）

```powershell
$env:LLM_API_KEY="sk-..."          # DeepSeek / Kimi / Qwen 等
$env:LLM_BASE_URL="https://api.deepseek.com/v1"
$env:LLM_MODEL="deepseek-chat"
python pipeline/extract_patch.py 812092
```

无 Key 时只跑规则抽取（官方公告的「x → y」数值行格式规整，规则已能覆盖大部分）。

## 加 RSA 签名（二期）

```powershell
openssl genrsa -out data_private.pem 2048
openssl rsa -in data_private.pem -pubout -out data_public.pem
python pipeline/publish_release.py ... --private-key data_private.pem
```

把 `data_public.pem` 放进 App 的 `res/raw/`，Java 侧用 `SHA256withRSA` 验签。
私钥只放发布机/CI Secret，绝不能进 APK。

## 托管发布包

`pipeline/out/publish/` 整个目录对应线上路径 `/wzjs/v1/`，任选静态托管：

- **GitHub Pages / Releases**（免费，MVP）：`git add pipeline/out/publish && git commit`，或上传到 Release。
- **腾讯云 COS + CDN**：`coscmd upload -r pipeline/out/publish/ /wzjs/v1/`
- **Cloudflare R2**：`rclone copy pipeline/out/publish r2:wzjs/v1`
- **自建 Nginx**：直接把目录拷到站点根目录。

manifest 建议 `Cache-Control: public, max-age=300`；`releases/**` 不可变，可长缓存。

## 定时任务示例（GitHub Actions）

```yaml
name: wzjs-data-update
on:
  schedule:
    - cron: "15 */6 * * *"   # 每 6 小时
  workflow_dispatch: {}
jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install playwright && playwright install chromium
      - run: python pipeline/fetch_sources.py
      - run: python pipeline/fetch_article.mjs $(python -c "import json;print(json.load(open('pipeline/out/source_report.json'))['patches'][0]['tid'])")
      - run: python pipeline/extract_patch.py <tid>
      # 审核：diff 结果作为 PR 提交，人工 review 后合并再 publish
      - run: python pipeline/publish_release.py --version $(date +%Y.%m.%d).1
      - uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: pipeline/out/publish
```

> 生产建议：采集/抽取只生成「草稿 + diff」，人工审核通过后再触发 publish，避免 LLM 幻觉直接上线。

## 与 App 对接（下一步）

当前 App（V2.0.3）的 data.json 是打包进 JS 的，需要：
1. 数据改为运行时 `fetch('/data/data.json')`（本地 HTTP 服务新路由，见架构文档第 6 节）；
2. 新增 Java `UpdateManager`：拉 manifest → 校验 sha256/签名 → 写 `files/data/<ver>` → 原子切换 → 通知页面刷新；
3. 设置页加「数据与更新」（版本号/检查更新/更新日志/恢复内置）。

这套改动即架构文档里的 **P0（0.5~1 天）**，完成后你改完数据只用跑管线发布，不用重发 APK。
