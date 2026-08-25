"""Offline regression checks for WeChat evidence metadata and batch failures."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "wechat-article-exporter" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fetch = load_module("fetch_article", SCRIPT_DIR / "fetch_article.py")
batch = load_module("batch_fetch", SCRIPT_DIR / "batch_fetch.py")

raw_text = "规划指标仅为待核验材料。"
content = fetch._build_json_export(
    title="离线测试文章",
    author="测试账号",
    published_at="2026-08-25",
    url="https://mp.weixin.qq.com/s/offline-smoke",
    article_id="offline-smoke",
    summary="",
    cover_url="",
    topic="",
    is_original="否",
    fetched_at="2026-08-25 11:00:00",
    raw_text=raw_text,
    fetch_status="success",
    fetch_note="离线回归测试",
)
article = {
    "title": "离线测试文章",
    "article_id": "offline-smoke",
    "format": "json",
    "content": content,
}
payload = json.loads(article["content"])

required = {
    "标题", "作者", "发布日期", "原链接", "抓取日期", "正文SHA256",
    "正文长度", "抓取状态", "备注", "正文",
}
assert required.issubset(payload)
assert payload["抓取状态"] == "success"
assert payload["正文长度"] == len(payload["正文"])
assert payload["正文SHA256"] == hashlib.sha256(
    payload["正文"].encode("utf-8")
).hexdigest()

previous_cwd = Path.cwd()
with tempfile.TemporaryDirectory() as temporary:
    os.chdir(temporary)
    try:
        saved = Path(fetch.save_article(article)).resolve()
        saved.relative_to(Path(temporary).resolve())

        def fail_fetch(*args, **kwargs):
            raise RuntimeError("offline failure")

        batch.fetch_article = fail_fetch
        result = batch.fetch_batch(
            ["https://mp.weixin.qq.com/s/offline-failure"],
            ["markdown"],
        )
        assert result["total"] == 1
        assert result["success"] == []
        assert len(result["failed"]) == 1
        assert result["failed"][0]["format"] == "markdown"
        assert result["failed"][0]["error"] == "offline failure"
    finally:
        os.chdir(previous_cwd)

print("wechat offline smoke passed")
