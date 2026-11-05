# 一键：采集官方数据 -> 抓公告正文 -> 抽取 -> 发布包 -> 复制到 GitHub Pages 数据仓库 -> git push
#
# 用法（在应用仓库根目录运行）：
#   powershell -ExecutionPolicy Bypass -File pipeline\github-pages\publish_to_pages.ps1 `
#       -RepoPath D:\wzjs-data -NoPush
#
# 首次使用前请先按 pipeline/github-pages/README.md 建好数据仓库并配置 Pages。
param(
    [Parameter(Mandatory = $true)][string]$RepoPath,
    [string]$Version = "",
    [string]$Tid = "",
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent  # wangzhe-apk/
Set-Location $root

$py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'py' }
Write-Host '== 1/5 采集官方数据 =='
& $py pipeline/fetch_sources.py
if ($LASTEXITCODE -ne 0) { throw 'fetch_sources failed' }

$reportPath = 'pipeline/out/source_report.json'
$report = Get-Content $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Tid) {
    if ($report.patches -and $report.patches.Count -gt 0) {
        $Tid = [string]$report.patches[0].tid
        $titleHint = $report.patches[0].title
    } else {
        throw '未找到版本更新公告，可稍后重试或手动指定 -Tid'
    }
} else {
    $titleHint = ''
}
Write-Host ("   最新公告 tid = " + $Tid + "  " + $titleHint)

Write-Host '== 2/5 无头浏览器渲染公告正文 =='
if (Get-Command node -ErrorAction SilentlyContinue) {
    & node pipeline/fetch_article.mjs $Tid
} else {
    & $py pipeline/fetch_article_playwright.py $Tid
}
if ($LASTEXITCODE -ne 0) { throw 'fetch_article failed' }

Write-Host '== 3/5 结构化抽取 =='
& $py pipeline/extract_patch.py $Tid
if ($LASTEXITCODE -ne 0) { throw 'extract_patch failed' }

Write-Host '== 4/5 生成发布包 =='
if (-not $Version) {
    $Version = (Get-Date -Format 'yyyy.MM.dd') + '.1'
}
$article = Get-Content "pipeline/out/articles/$Tid.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$patchDate = (Get-Date -Format 'yyyy-MM-dd')
& $py pipeline/publish_release.py `
    --version $Version `
    --data next/src/data/data.json `
    --patches "pipeline/out/extracted/$Tid.json" `
    --patch-id $Tid `
    --patch-title $article.title `
    --patch-date $patchDate `
    --source-url $article.sourceUrl `
    --notes ("数据更新：" + $article.title)
if ($LASTEXITCODE -ne 0) { throw 'publish_release failed' }

Write-Host '== 5/5 复制到数据仓库并提交 =='
$dst = Join-Path $RepoPath 'wzjs\v1'
if (-not (Test-Path (Join-Path $RepoPath '.git'))) {
    throw ("RepoPath 不是 git 仓库：" + $RepoPath)
}
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item 'pipeline/out/publish/*' $dst -Recurse

Push-Location $RepoPath
try {
    git add -A
    git commit -m ("data: " + $Version + " (" + $article.title + ")")
    if (-not $NoPush) {
        git push
        Write-Host '   已推送，等 GitHub Pages 部署后 App 即可检查更新'
    } else {
        Write-Host '   -NoPush：已提交到本地，未推送'
    }
} finally {
    Pop-Location
}
