# GitHub Pages 数据发布（一次配置，之后自动热更新）

App 端只认一个静态地址：`https://<用户名>.github.io/<数据仓库>/wzjs/v1/manifest.json`。
按下面步骤建一个**公开数据仓库**（只放发布产物，不放源码也可以），App 里填这个地址即可。

---

## 一、一次性配置

### 1. 建仓库

在 GitHub 新建公开仓库，例如 `wzjs-data`（名字随意，建议公开）。
本地克隆：

```powershell
git clone https://github.com/<用户名>/wzjs-data.git D:\wzjs-data
```

### 2. 准备数据仓库目录

把本应用的以下内容复制进数据仓库（保持相对路径）：

```
wzjs-data/
├── .github/workflows/update-data.yml     # 从 pipeline/github-pages/update-data.yml 复制
├── pipeline/                             # 复制应用仓库的 pipeline/ 目录
├── next/src/data/data.json               # 复制应用仓库的 next/src/data/data.json（发布脚本以此为数据源）
└── wzjs/v1/                              # 由发布脚本生成（首次可先手动跑一次）
```

> 说明：数据仓库里只放「数据 + 管线」，不需要打包 Android / 前端。

### 3. 开启 GitHub Pages

仓库 **Settings → Pages** → Source 选 **Deploy from a branch** → Branch 选 `main`，目录 `/ (root)` → Save。
等 1~2 分钟，得到地址：`https://<用户名>.github.io/wzjs-data/`。

### 4. 手动跑一次发布（先验证）

```powershell
cd D:\wzjs-data
pip install playwright
python -m playwright install chromium

python pipeline/fetch_sources.py
# 取最新版本公告 tid（示例输出里的 "11月5日版本更新公告 | tid=812092"）
python pipeline/fetch_article_playwright.py 812092
python pipeline/extract_patch.py 812092

python pipeline/publish_release.py --version 2026.11.05.1 `
  --data next/src/data/data.json `
  --patches pipeline/out/extracted/812092.json `
  --patch-id 812092 --patch-title "11月5日版本更新公告" --patch-date 2026-11-04 `
  --source-url "https://pvp.qq.com/web201706/newsdetail.shtml?G_Biz=18&tid=812092" `
  --notes "11-05 版本更新"

# 发布产物复制到 Pages 目录
Remove-Item wzjs\v1 -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force wzjs\v1 | Out-Null
Copy-Item pipeline\out\publish\* wzjs\v1 -Recurse

git add -A
git commit -m "data: 2026.11.05.1"
git push
```

等 Pages 部署完成，访问
`https://<用户名>.github.io/wzjs-data/wzjs/v1/manifest.json` 能看到 JSON 即成功。

### 5. App 里填地址

App → 更多 → 设置 → **数据与更新** → 数据源地址填：

```
https://<用户名>.github.io/wzjs-data/wzjs/v1/
```

点「保存地址」→「检查更新」。之后每次启动（6 小时节流）会自动检查；
有新版会下载、校验 sha256、整页重载，设置页能看到新数据版本与版本公告。

---

## 二、定时自动更新（GitHub Actions）

把 `pipeline/github-pages/update-data.yml` 复制到数据仓库的
`.github/workflows/update-data.yml`，之后每 6 小时自动跑：

1. 拉官方英雄/装备/公告列表；
2. 比对 `wzjs/v1/manifest.json` 里已发布的公告 tid，**没有新公告就直接跳过**（不产生垃圾提交）；
3. 有新公告 → 无头浏览器抓正文 → 规则/LLM 抽取 → 生成新版本发布包；
4. 提交并推送到 `main`，Pages 自动部署，App 下次启动自动更新。

需要人工复核时：把 workflow 最后一步的 `git push` 去掉，改为生成 PR 草稿，人工合并后再发布。
（LLM 抽取的 `evidence`/`warnings` 在 `pipeline/out/extracted/<tid>.json`，看得懂再发。）

### 可选：LLM 增强抽取

在数据仓库 **Settings → Secrets and variables → Actions** 添加：

- `LLM_API_KEY`：DeepSeek / Kimi / Qwen 的 API Key
- `LLM_BASE_URL`（可选）：默认 `https://api.deepseek.com/v1`
- `LLM_MODEL`（可选）：默认 `deepseek-chat`

workflow 会把它们注入给 `extract_patch.py`；没有 Key 时规则抽取照常工作。

---

## 三、发布版本号约定

- `dataVersion`：`YYYY.MM.DD.N`（日期 + 当日序号），App 按数字比较大小；
- `data.json` 里的 `version` 会被发布脚本改写成 `dataVersion`，首页/设置里显示的就是它；
- `manifest.patch` 带公告 id/标题/日期/来源链接，App 设置页「本版公告」可直接跳原文。

## 四、回滚

- 数据侧：把 `wzjs/v1/manifest.json` 与 `releases/` 回退到上一个 commit 并 push；
- App 侧：设置 → 数据与更新 → 「恢复内置数据」，立即回到 APK 内置快照。
