# 王者教研室 · 数据仓库（wzjs-data）

这个仓库只做一件事：**给「王者教研室」App 提供可热更新的数据包**。
App 启动时从这里拉 `manifest.json` + `data.json`（做 SHA-256 校验），校验通过后整页刷新生效；
断网/校验失败自动继续用 APK 内置数据，不影响使用。

- App 拉取地址（在 App「设置 → 数据与更新 → 数据源地址」里填这个）：
  `https://caoj47883-create.github.io/wzjs-data/wzjs/v1/`
- 需要 App 版本 **V2.1.0+**（纯本地 + 联网热更新）
- 当前线上版本：`2026.11.06.103` · 公告：11月5日版本更新公告 · 数据快照 2026-11-04

---

## 一、目录结构

```
wzjs-data/
├── .github/workflows/update-data.yml   # 自动更新 + 手动补发/重抽（tid / force 输入）
├── pipeline/                           # 采集、正文渲染、LLM 抽取、发布脚本
│   ├── fetch_sources.py                # 官方数据/公告采集（CMC 公告接口优先）
│   ├── fetch_article_playwright.py     # 无头浏览器渲染公告正文（CI 用）
│   ├── extract_patch.py                # 结构化抽取（有 LLM Key 走大模型，否则规则兜底）
│   └── publish_release.py              # 生成 manifest + releases/<版本>/
├── next/src/data/data.json             # 发布用的基础数据快照
└── wzjs/v1/                            # GitHub Pages 实际发布目录
    ├── manifest.json                   # App 拉取入口（版本/文件/sha256/公告信息）
    ├── latest.json                     # 同 manifest，便于人看
    └── releases/<dataVersion>/
        ├── data.json                   # 数据包（heroes/items/comps/...）
        ├── patches.json                # 本版公告抽取结果（更新日志来源）
        └── release.json                # 发布说明
```

**不要手动改 `wzjs/v1/` 里的 JSON**：manifest 里的 sha256 必须和文件字节严格一致，
手动编辑很容易触发 App 端「哈希校验失败」而拒绝更新。要改数据请走下面的发布流程。

---

## 二、自动更新（默认每 6 小时）

`.github/workflows/update-data.yml`：

1. `fetch_sources.py` 拉官方数据/公告；
   - **公告来源优先用官方 CMC 接口**（`serviceId=18`、公告频道 `chanid=1762`、官网 md5 签名），
     因为官网静态页 `newsindex.shtml` 可能被 CDN 缓存到旧版本（曾实测缓存到 10 月 28 日，导致漏掉 11/5 公告）；
   - 静态页解析只作兜底，日志里会标注 `via CMC api` 或 `page parse（兜底，可能滞后）`。
2. 找出最新的「版本更新公告」tid，和已发布 manifest 里的 `patch.id` 比较：
   - 新 tid > 已发布 tid → 发布；
   - 否则跳过（**防止网络异常拿到旧列表时把线上数据降级**）。
3. 渲染公告正文 → 抽取 → 生成新版本 → 提交并推送 → Pages 自动部署。
4. App 下次启动（6 小时节流）检查到新版本 → 下载校验 → 刷新界面。

版本号规则：`YYYY.MM.DD.N`，CI 使用 `N = GITHUB_RUN_NUMBER + 100`（避免和手工版本冲突），
App 按数字比较大小，所以新版本必须大于线上版本。

---

## 三、手动补发 / 指定公告发布

**什么时候需要手动补发？**

- 自动检测没跟上（官网接口缓存/发布延迟），线上数据不是最新公告；
- 想把某条公告重新发一次（例如第一次抽取质量不好，想走 LLM 重抽）；
- 想修正错误数据（发错公告、数据异常）；
- 补发历史公告（App 用户数据落后）。

**操作方式（任选一种）**

### 方式 1：GitHub 网页（推荐，最简单）

1. 打开仓库 → **Actions** → 左侧选 **wzjs-data-update** → 右侧 **Run workflow**；
2. 填两个输入：
   - `tid`：公告 id，例如 `812092`（留空 = 自动检测最新公告）
   - `force`：勾选（允许 tid ≤ 已发布版本，用于补发/重抽/修正）
3. 点 **Run workflow**。等约 1 分钟，看到绿色 ✅ 即发布完成；
4. 约 1~2 分钟后（Pages 部署 + CDN 缓存）App 检查更新即可拿到新版本。

> 怎么找公告 tid：官网新闻列表里打开公告，URL 里的 `tid=` 就是；
> 或看 Actions 日志里 `latest patch: <tid>` 那一行。

### 方式 2：命令行 gh CLI

```bash
gh workflow run update-data.yml \
  -f tid=812092 \
  -f force=true \
  --repo caoj47883-create/wzjs-data
```

看运行状态：

```bash
gh run list --repo caoj47883-create/wzjs-data --limit 5
gh run watch --repo caoj47883-create/wzjs-data
```

### 方式 3：GitHub REST API（脚本/其他机器触发）

```bash
curl -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/caoj47883-create/wzjs-data/actions/workflows/update-data.yml/dispatches \
  -d '{"ref":"main","inputs":{"tid":"812092","force":"true"}}'
```

Token 需要 `repo` + `workflow` 权限（经典 PAT 勾选 `repo`、`workflow` 即可）。

### 参数说明

| 参数 | 作用 |
| --- | --- |
| `tid` | 指定要发布/重抽的公告 id；留空 = 自动检测最新版本更新公告 |
| `force` | `true` 时允许 `tid <= 已发布 tid` 发布（补发/重抽/修正都靠它）；不勾则只允许 tid 递增 |

> `force=true` 会生成一个**新版本号**（`run_number + 100`），不会覆盖旧版本，App 端仍是正常升级流程，可随时回滚。

---

## 四、LLM 重抽（让更新日志更详细）

`extract_patch.py` 的行为：

- 没配 LLM Key：规则抽取（只覆盖 `x → y` 数值行，约 10 条）；
- 配了 `LLM_API_KEY`：调用 OpenAI 兼容接口（默认 DeepSeek），输出带
  `field / from / to / direction / impact` 的结构化改动，约 25~40 条，更新日志更可读。

**配置（一次性）**：仓库 **Settings → Secrets and variables → Actions → New repository secret**

| Secret | 必填 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 是（用 LLM 时） | 如 DeepSeek / Kimi / 通义 的 API Key |
| `LLM_BASE_URL` | 否 | 默认 `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | 默认 `deepseek-chat` |

**触发重抽**：按「方式 1/2/3」手动跑一次，`tid=最新公告id`、`force=true` 即可。
它会重新渲染正文 → LLM 抽取 → 发布新版本（例如 `2026.11.06.103`）。

**怎么确认是 LLM 抽的？**

```bash
curl -s https://caoj47883-create.github.io/wzjs-data/wzjs/v1/manifest.json | jq '.dataVersion, .patch.title'
curl -s https://caoj47883-create.github.io/wzjs-data/wzjs/v1/releases/<版本>/patches.json \
  | jq '{changes: (.changes|length), llm: .llm._model, first: .changes[0]}'
```

`changes` 数量明显变多、每条带 `field/impact`、且 `llm._model` 有值 → 就是 LLM 抽取。
App 设置页的「更新日志（N 条）」数量也会同步变化。

---

## 五、发布后验证

### 1. 线上文件校验

```bash
python - <<'PY'
import json, hashlib, urllib.request
base = "https://caoj47883-create.github.io/wzjs-data/wzjs/v1/"
m = json.loads(urllib.request.urlopen(base + "manifest.json").read())
print(m["dataVersion"], m["patch"]["title"])
for name, spec in m["files"].items():
    data = urllib.request.urlopen(base + spec["url"]).read()
    print(name, len(data), hashlib.sha256(data).hexdigest() == spec["sha256"])
PY
```

### 2. App 端验证

App → 更多 → 设置 → 数据与更新：

- 当前数据版本 = 线上 `dataVersion`；
- 数据来源 = 联网更新；
- 本版公告 / 更新时间正确；
- 更新日志条数与 `patches.json` 的 `changes` 数一致。

### 3. 缓存说明

`manifest.json` 由 GitHub Pages 提供 `Cache-Control: max-age=600`，
App 拉取时会加 `_t` 时间戳参数破缓存；Pages 部署 + CDN 生效一般 1~3 分钟。
刚发布后如果 App 还显示旧版本，等 1 分钟再点「检查更新」。

---

## 六、回滚

**数据回滚（推荐）**：在仓库里把 `wzjs/v1/` 恢复到上一个正常提交（`git revert <commit>` 或网页 Revert），
推送后 Pages 自动部署；App 下次检查会拿到回滚后的版本（版本号变小不会自动降级，
需要 App 端「恢复内置数据」或发布一个版本号更大的修复包）。

**App 本地回滚**：App → 设置 → 数据与更新 → **恢复内置数据**，
立即回到 APK 内置快照（收藏/设置不受影响）。

---

## 七、常见问题

| 现象 | 处理 |
| --- | --- |
| Actions 日志显示 `via page parse（兜底，可能滞后）` | 官方 CMC 接口暂时失败，数据可能不是最新；手动 `tid+force` 补发，或等接口恢复 |
| 日志显示 `latest tid <= published, skip` | 正常保护逻辑；确认官网是否有新公告；需要重发就加 `force=true` |
| CMC 接口签名失效（fetch_sources 报错） | token 在官网 `newsindex.js` 的 `makeSign` 里，更新 `pipeline/fetch_sources.py` 的 `CMC_TOKEN`；同时保留静态页兜底 |
| App 提示「哈希校验失败」 | 不要手改 `wzjs/v1` 文件；重新用 `publish_release.py` 生成后发布（manifest 与文件必须同一轮生成） |
| App 看不到更新 | 检查 App 数据源地址末尾有没有 `/`；等 Pages 缓存；手动「检查更新」；确认 App ≥ 2.1.0 |
| Actions 推送失败 | 检查仓库 **Settings → Actions → General → Workflow permissions** 是否 Read and write |
| 本地 clone 无法 git fetch（网络问题） | GitHub Actions 和网页操作不依赖本地；恢复后 `git fetch origin && git reset --hard origin/main` 同步 |
| 旧 release 太多想清理 | 保留最近 3 个即可；只删 `wzjs/v1/releases/` 下旧目录，不动 manifest 指向的版本 |

---

## 八、维护清单（发新版本时照做）

- [ ] 等自动更新跑完（或手动 dispatch）→ 确认 Actions 绿色 ✅
- [ ] `manifest.json` 的 `dataVersion`、`patch.title`、`patch.date` 正确
- [ ] `patches.json` 条数合理（LLM 25+ / 规则 ~10）
- [ ] App「检查更新」能升到新版本、更新日志/公告正确
- [ ] 如果发错：`git revert` 或再发一版修正，并在 App 端验证
