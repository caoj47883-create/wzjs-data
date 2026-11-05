#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
王者教研室 · 数据发布打包（RAG 管线第 3 步 / P0 热更新）

把 data.json（+ 可选 patches.json）打包成 App 可拉取的发布目录：
    pipeline/out/publish/wzjs/v1/
    ├── manifest.json
    └── releases/<dataVersion>/
        ├── data.json
        ├── patches.json   (可选)
        └── release.json

用法：
    python pipeline/publish_release.py --version 2026.11.05.1 \
        --data next/src/data/data.json \
        --patches pipeline/out/extracted/812092.json \
        --notes "11月5日版本：敖隐/艾琳等英雄调整"

签名（可选，二期）：
    --private-key data_private.pem   对 manifest 的规范化 bytes 做 SHA256withRSA 签名
    （可用 openssl 生成密钥：openssl genrsa -out data_private.pem 2048）
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest, key_path):
    """用 openssl dgst 对规范化后的 manifest 签名（RSA-SHA256），返回 base64。"""
    payload = canonical_bytes({k: v for k, v in manifest.items() if k != "signature"})
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
        tmp.write(payload)
        tmp_path = tmp.name
    try:
        sig_path = tmp_path + ".sig"
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path, "-out", sig_path, tmp_path],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError("openssl sign failed: " + result.stderr.decode("utf-8", "replace"))
        with open(sig_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    finally:
        for p in (tmp_path, tmp_path + ".sig"):
            try:
                os.remove(p)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="dataVersion，如 2026.11.05.1")
    ap.add_argument("--data", default=os.path.join(BASE, "next", "src", "data", "data.json"))
    ap.add_argument("--patches", default=None, help="公告抽取结果 JSON（会写入 patches.json）")
    ap.add_argument("--notes", default="", help="发布说明")
    ap.add_argument("--patch-id", default=None)
    ap.add_argument("--patch-title", default=None)
    ap.add_argument("--patch-date", default=None)
    ap.add_argument("--source-url", default=None)
    ap.add_argument("--min-app-version", default="2.0.3")
    ap.add_argument("--private-key", default=None, help="RSA 私钥 PEM 路径（可选）")
    ap.add_argument("--out", default=os.path.join(BASE, "pipeline", "out", "publish"))
    args = ap.parse_args()

    out_root = args.out
    ver = args.version
    version_dir = os.path.join(out_root, "releases", ver)
    os.makedirs(version_dir, exist_ok=True)

    # 1. 数据包
    if not os.path.exists(args.data):
        raise SystemExit("data.json 不存在: " + args.data)
    data_dst = os.path.join(version_dir, "data.json")
    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    if "heroes" not in data or "items" not in data:
        raise SystemExit("data.json 缺少 heroes/items 字段，拒绝发布")
    # 把 dataVersion 写进数据包本身，App 内显示/比较都以此为准
    data["version"] = ver
    if args.patch_date:
        data["snapshot"] = args.patch_date
    with open(data_dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    files = {
        "data.json": {
            "sha256": sha256_file(data_dst),
            "size": os.path.getsize(data_dst),
            "url": "releases/%s/data.json" % ver,
        }
    }

    patches_info = None
    if args.patches and os.path.exists(args.patches):
        patches_dst = os.path.join(version_dir, "patches.json")
        shutil.copyfile(args.patches, patches_dst)
        files["patches.json"] = {
            "sha256": sha256_file(patches_dst),
            "size": os.path.getsize(patches_dst),
            "url": "releases/%s/patches.json" % ver,
        }
        with open(patches_dst, encoding="utf-8") as f:
            patches_info = json.load(f).get("changes", [])

    # 2. 发布说明
    release = {
        "dataVersion": ver,
        "publishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "notes": args.notes,
        "changeCount": len(patches_info or []),
        "heroes": len(data.get("heroes", [])),
        "items": len(data.get("items", [])),
        "comps": len(data.get("comps", [])),
    }
    with open(os.path.join(version_dir, "release.json"), "w", encoding="utf-8") as f:
        json.dump(release, f, ensure_ascii=False, indent=2)

    # 3. manifest
    manifest = {
        "schemaVersion": 1,
        "dataVersion": ver,
        "engineVersion": "1.0.0",
        "minAppVersion": args.min_app_version,
        "publishedAt": release["publishedAt"],
        "notes": args.notes,
        "patch": {
            "id": args.patch_id,
            "title": args.patch_title,
            "date": args.patch_date,
            "sourceUrl": args.source_url,
        },
        "files": files,
    }
    if args.private_key:
        manifest["signature"] = {
            "alg": "RSA-SHA256",
            "keyId": "wzjs-data-v1",
            "value": sign_manifest(manifest, args.private_key),
        }

    manifest_path = os.path.join(out_root, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    # 方便 CDN/静态托管：latest.json 同内容
    shutil.copyfile(manifest_path, os.path.join(out_root, "latest.json"))

    print("== 发布包已生成 ==")
    print("版本:", ver)
    print("目录:", version_dir)
    print("manifest:", manifest_path)
    print("文件:")
    for name, spec in files.items():
        print("  %-14s %9d B  sha256=%s" % (name, spec["size"], spec["sha256"][:16] + "…"))
    print("签名:", "RSA-SHA256 (%d chars)" % len(manifest["signature"]["value"]) if "signature" in manifest else "未签名（MVP 可先只校验 sha256）")


if __name__ == "__main__":
    main()
