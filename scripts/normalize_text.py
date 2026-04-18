#!/usr/bin/env python3
"""多形式の作品集を UTF-8 plain text に正規化する。

対応形式: .txt / .pdf / .epub / .html / .htm
青空文庫の特殊記法（ルビ・注記）を除去する。
文字コードは charset-normalizer で自動判定する（Shift_JIS の aozora 対応）。

使い方:
    python3 normalize_text.py <入力ディレクトリ|ファイル> [--out-dir DIR]

出力:
    --out-dir 未指定時は <入力>_normalized/ に同階層構造で .txt を出す。
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

try:
    from charset_normalizer import from_bytes
    HAS_CHARSET = True
except ImportError:
    HAS_CHARSET = False

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup
    HAS_EPUB = True
except ImportError:
    HAS_EPUB = False

try:
    from bs4 import BeautifulSoup as _BS  # noqa: F401
    HAS_HTML = True
except ImportError:
    HAS_HTML = False


# 青空文庫記法（Aozora 判定時のみ適用）
RUBY_PIPE = re.compile(r"｜([^《]+?)《[^》]+?》")       # ｜漢字《るび》 → 漢字
RUBY_INLINE = re.compile(r"([一-龥々〆ヵヶ]+?)《[^》]+?》")  # 漢字《るび》 → 漢字
ANNOTATION = re.compile(r"［＃[^］]*?］")                # ［＃...］ 除去
SOKOBON_SPLIT = re.compile(r"\n[ \u3000]*底本[：:].*", re.DOTALL)  # 底本以降は切る
# 冒頭の -------- 区切り 2 本で挟まれたメタブロック除去。改行統一後に適用する想定。
HEADER_SEP = re.compile(r"\A.*?\n-{5,}\n.*?\n-{5,}\n", re.DOTALL)
AOZORA_DASH = re.compile(r"^-{5,}\s*$", re.MULTILINE)


def detect_and_decode(raw: bytes) -> tuple[str, str]:
    """バイト列を charset_normalizer で判定し UTF-8 相当の str に戻す。"""
    # BOM 優先
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace"), "utf-16"

    if HAS_CHARSET:
        result = from_bytes(raw).best()
        if result is not None:
            return str(result), result.encoding or "unknown"

    # フォールバック：日本語候補を順に試す
    for enc in ("utf-8", "cp932", "shift_jis", "euc-jp", "iso-2022-jp"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def normalize_common(text: str) -> str:
    """形式を問わない共通正規化：BOM / ゼロ幅 / CRLF の除去。"""
    text = text.replace("\ufeff", "")
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def is_aozora(text: str) -> bool:
    """青空文庫テキストかを簡易判定する。2 つ以上の特徴を満たせば真。"""
    signs = 0
    if "《" in text and "》" in text:
        signs += 1
    if "［＃" in text:
        signs += 1
    if re.search(r"\n底本[：:]", text):
        signs += 1
    if AOZORA_DASH.search(text):
        signs += 1
    return signs >= 2


def aozora_cleanup(text: str) -> str:
    """青空文庫記法を除去する。呼び出し前に改行を \n へ統一しておくこと。"""
    text = HEADER_SEP.sub("", text, count=1)
    text = SOKOBON_SPLIT.sub("", text, count=1)
    text = RUBY_PIPE.sub(r"\1", text)
    text = RUBY_INLINE.sub(r"\1", text)
    text = ANNOTATION.sub("", text)
    return text


def tidy(text: str) -> str:
    """最終仕上げ：連続空行の圧縮・前後空白の削除。"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def extract_txt(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    text, enc = detect_and_decode(raw)
    return text, enc


def extract_pdf(path: Path) -> tuple[str, str]:
    if not HAS_PDF:
        raise RuntimeError("pdfplumber 未インストール")
    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            parts.append(t)
    return "\n".join(parts), "pdf"


def extract_html(path: Path) -> tuple[str, str]:
    if not HAS_HTML:
        raise RuntimeError("beautifulsoup4 未インストール")
    raw = path.read_bytes()
    text, enc = detect_and_decode(raw)
    soup = BeautifulSoup(text, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    # 青空 HTML は <ruby><rb>漢字</rb><rt>るび</rt></ruby>
    for rt in soup.find_all("rt"):
        rt.decompose()
    return soup.get_text("\n"), enc


def extract_epub(path: Path) -> tuple[str, str]:
    if not HAS_EPUB:
        raise RuntimeError("ebooklib / beautifulsoup4 未インストール")
    book = epub.read_epub(str(path))
    parts: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "lxml")
        for rt in soup.find_all("rt"):
            rt.decompose()
        parts.append(soup.get_text("\n"))
    return "\n".join(parts), "epub"


EXTRACTORS = {
    ".txt": extract_txt,
    ".pdf": extract_pdf,
    ".html": extract_html,
    ".htm": extract_html,
    ".epub": extract_epub,
}


def collect_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for ext in EXTRACTORS:
        files.extend(root.rglob(f"*{ext}"))
    # .txt が既に正規化済みのものは除外（出力と入力が重ならないように）
    return sorted(files)


def process(
    src: Path,
    src_root: Path,
    out_root: Path,
    aozora_mode: str = "auto",   # "auto" | "force" | "off"
) -> tuple[bool, int, str, bool]:
    ext = src.suffix.lower()
    extractor = EXTRACTORS.get(ext)
    if extractor is None:
        return False, 0, f"unsupported: {ext}", False
    try:
        text, enc = extractor(src)
    except Exception as e:
        return False, 0, f"extract error ({type(e).__name__}): {e}", False

    text = normalize_common(text)
    aozora_applied = False
    if aozora_mode == "force" or (aozora_mode == "auto" and is_aozora(text)):
        text = aozora_cleanup(text)
        aozora_applied = True
    text = tidy(text)

    rel = src.relative_to(src_root) if src != src_root else Path(src.name)
    out_path = (out_root / rel).with_suffix(".txt")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return True, len(text), enc, aozora_applied


def main() -> int:
    p = argparse.ArgumentParser(description="多形式テキストを UTF-8 plain に正規化")
    p.add_argument("input", type=Path, help="入力ディレクトリまたはファイル")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="出力ディレクトリ。未指定時は <入力>_normalized/")
    p.add_argument("--quiet", action="store_true", help="ファイルごとのログを抑制")
    p.add_argument("--aozora", choices=["auto", "force", "off"], default="auto",
                   help="青空文庫記法クリーンアップ。auto=自動検出（既定）/force=必ず適用/off=無効")
    args = p.parse_args()

    src_root: Path = args.input.resolve()
    if not src_root.exists():
        print(f"error: {src_root} not found", file=sys.stderr)
        return 1

    out_root = args.out_dir.resolve() if args.out_dir else (
        src_root.parent / f"{src_root.name}_normalized"
        if src_root.is_dir()
        else src_root.parent / f"{src_root.stem}_normalized"
    )
    out_root.mkdir(parents=True, exist_ok=True)

    files = collect_files(src_root)
    if not files:
        print(f"warn: no supported files under {src_root}", file=sys.stderr)
        return 0

    if not HAS_CHARSET:
        print("warn: charset-normalizer 未インストール。encoding 判定が弱まります",
              file=sys.stderr)

    total_chars = 0
    ok_count = 0
    ng_count = 0
    aozora_count = 0
    enc_tally: dict[str, int] = {}

    for src in files:
        ok, chars, info, was_aozora = process(src, src_root, out_root, args.aozora)
        if ok:
            ok_count += 1
            total_chars += chars
            enc_tally[info] = enc_tally.get(info, 0) + 1
            if was_aozora:
                aozora_count += 1
            if not args.quiet:
                mark = " [aozora]" if was_aozora else ""
                print(f"[ok] {src.relative_to(src_root)}: {chars:,} chars ({info}){mark}")
        else:
            ng_count += 1
            print(f"[ng] {src.relative_to(src_root)}: {info}", file=sys.stderr)

    print(f"\n-- summary --", file=sys.stderr)
    print(f"output dir : {out_root}", file=sys.stderr)
    print(f"ok / ng    : {ok_count} / {ng_count}", file=sys.stderr)
    print(f"total chars: {total_chars:,}", file=sys.stderr)
    print(f"encodings  : {enc_tally}", file=sys.stderr)
    print(f"aozora clean applied: {aozora_count} / {ok_count} files", file=sys.stderr)
    return 0 if ng_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
