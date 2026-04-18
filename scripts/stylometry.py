#!/usr/bin/env python3
"""正規化済みテキスト（または任意のテキスト）から L1-L3 の文体統計を算出する。

使い方:
    python3 stylometry.py <ディレクトリ|ファイル> [--out FILE] [--tokenizer auto|fugashi|regex]

出力:
    stdout に JSON（pretty-print）。--out 指定時はファイルに保存。

設計原則:
- 入力は UTF-8 plain text 前提だが、検出に失敗した場合は charset-normalizer で自動復号する
- fugashi があれば使う。無ければ正規表現ベースの簡易トークナイザにフォールバック
- 主語省略率はヒューリスティック推定（絶対値ではない）
- JSON に limitations フィールドで既知の不精確さを必ず記録する
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from charset_normalizer import from_bytes
    HAS_CHARSET = True
except ImportError:
    HAS_CHARSET = False

try:
    import fugashi
    HAS_FUGASHI = True
except ImportError:
    HAS_FUGASHI = False


# 監視対象の語彙
FIRST_PERSON = ["僕", "俺", "私", "わたくし", "わたし", "吾輩", "我", "あたし", "うち", "自分"]
SENTENCE_FINAL_PARTICLES = [
    "かしら", "ですもの", "なのだ", "のだ",
    "ね", "よ", "わ", "ぜ", "ぞ", "さ", "な", "の", "ぞ",
]
COMMON_ENDINGS = {
    "de_aru": re.compile(r"である[。！？」]"),
    "da": re.compile(r"だ[。！？」]"),
    "da_past": re.compile(r"だった[。！？」]"),
    "ta": re.compile(r"た[。！？」]"),
    "masu": re.compile(r"ます[。！？」]"),
    "desu": re.compile(r"です[。！？」]"),
}

# 文字種範囲
HIRAGANA = re.compile(r"[\u3040-\u309f]")
KATAKANA = re.compile(r"[\u30a0-\u30ff\u31f0-\u31ff]")
KANJI = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf々〆ヵヶ]")
LATIN = re.compile(r"[A-Za-z]")
DIGIT = re.compile(r"[0-9０-９]")

# 句読点
PUNCT_CHARS = "、。！？「」『』（）［］【】〈〉《》…—‥ー・：；"
PUNCT_PATTERN = re.compile(f"[{re.escape(PUNCT_CHARS)}]")

# オノマトペ候補（弱いヒューリスティック）
# - カタカナ連続 3 文字以上
# - ひらがな反復（ふわふわ、ぐるぐる等）
KATA_SEQ = re.compile(r"[\u30a0-\u30ff]{3,}")
HIRA_REPEAT = re.compile(r"([\u3040-\u309f]{2})\1")

# 文区切り
SENTENCE_SPLIT = re.compile(r"[。！？\n]+")

# 体言止め：文末が漢字・カタカナで終わる（ざっくり）
TAIGEN_DOME = re.compile(r"[\u4e00-\u9fff\u30a0-\u30ff]{2,}$")


# -------- テキスト読み込み --------

def read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        if HAS_CHARSET:
            res = from_bytes(raw).best()
            if res is not None:
                return str(res)
        for enc in ("cp932", "shift_jis", "euc-jp", "iso-2022-jp"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


def collect_texts(root: Path) -> list[tuple[Path, str]]:
    if root.is_file():
        return [(root, read_text(root))]
    out: list[tuple[Path, str]] = []
    for p in sorted(root.rglob("*.txt")):
        if not p.is_file():
            continue
        out.append((p, read_text(p)))
    return out


# -------- トークナイザ --------

class Tokenizer:
    def __init__(self, mode: str = "auto"):
        self.mode = mode
        self.tagger = None
        if mode in ("auto", "fugashi") and HAS_FUGASHI:
            try:
                self.tagger = fugashi.Tagger()
                self.name = "fugashi"
            except Exception as e:
                if mode == "fugashi":
                    raise
                print(f"warn: fugashi init failed ({e}); falling back to regex",
                      file=sys.stderr)
                self.name = "regex"
        else:
            if mode == "fugashi":
                raise RuntimeError("fugashi が未インストール")
            self.name = "regex"

    def tokenize(self, text: str) -> list[tuple[str, str]]:
        """(surface, pos) のリストを返す。regex 時は pos は '?' 固定。"""
        if self.tagger is not None:
            out = []
            for w in self.tagger(text):
                pos = w.feature.pos1 if hasattr(w.feature, "pos1") else "?"
                out.append((w.surface, pos))
            return out
        # 正規表現フォールバック：文字種で区切る
        tokens: list[tuple[str, str]] = []
        buf = ""
        last_class = ""
        for ch in text:
            if KANJI.match(ch):
                cls = "K"
            elif HIRAGANA.match(ch):
                cls = "h"
            elif KATAKANA.match(ch):
                cls = "k"
            elif LATIN.match(ch):
                cls = "L"
            elif DIGIT.match(ch):
                cls = "D"
            elif ch.isspace():
                cls = "s"
            else:
                cls = "p"
            if cls != last_class and buf:
                tokens.append((buf, "?"))
                buf = ""
            buf += ch
            last_class = cls
        if buf:
            tokens.append((buf, "?"))
        return tokens


# -------- L1 語彙 --------

def count_first_person(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pron in FIRST_PERSON:
        counts[pron] = len(re.findall(re.escape(pron), text))
    return counts


def count_sentence_final_particles(sentences: list[str]) -> dict[str, int]:
    counts = {p: 0 for p in SENTENCE_FINAL_PARTICLES}
    for s in sentences:
        # 文末の直前 3 文字くらいに終助詞があるかを見る
        tail = s.rstrip("。！？\n」』　 ")
        for p in SENTENCE_FINAL_PARTICLES:
            if tail.endswith(p):
                counts[p] += 1
                break
    return counts


def onomatopoeia_candidates(text: str, top: int = 30) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    c.update(KATA_SEQ.findall(text))
    c.update(m.group(0) for m in HIRA_REPEAT.finditer(text))
    # 1 文字 kata 擬態語はノイズなので除外済み
    return c.most_common(top)


def top_terms_tfidf(docs: list[list[str]], top: int = 100) -> list[dict]:
    """語の tf-idf。各 doc はトークン surface のリスト。doc 間で比較可能な語のみ残す。"""
    if not docs:
        return []
    N = len(docs)
    df: Counter[str] = Counter()
    tf_sum: Counter[str] = Counter()
    for doc in docs:
        seen = set()
        for t in doc:
            tf_sum[t] += 1
            if t not in seen:
                seen.add(t)
                df[t] += 1
    scores: list[tuple[str, float, int]] = []
    for term, tf in tf_sum.items():
        if len(term) < 2:
            continue
        if not any(KANJI.search(term) or HIRAGANA.search(term) or KATAKANA.search(term)
                   for _ in [0]):
            continue
        if PUNCT_PATTERN.search(term):
            continue
        idf = math.log((N + 1) / (df[term] + 1)) + 1
        scores.append((term, tf * idf, tf))
    scores.sort(key=lambda x: x[1], reverse=True)
    return [{"term": t, "tfidf": round(s, 4), "tf": tf} for t, s, tf in scores[:top]]


# -------- L2 構文 --------

def split_sentences(text: str) -> list[str]:
    raw = [s.strip() for s in SENTENCE_SPLIT.split(text)]
    return [s for s in raw if s]


def sentence_length_stats(sentences: list[str]) -> dict:
    if not sentences:
        return {"mean": 0, "median": 0, "std": 0, "count": 0}
    lens = sorted(len(s) for s in sentences)
    n = len(lens)
    mean = sum(lens) / n
    median = lens[n // 2] if n % 2 else (lens[n // 2 - 1] + lens[n // 2]) / 2
    var = sum((L - mean) ** 2 for L in lens) / n
    return {
        "mean": round(mean, 2),
        "median": median,
        "std": round(math.sqrt(var), 2),
        "count": n,
        "max": lens[-1],
        "min": lens[0],
    }


def ending_style_rates(sentences: list[str]) -> dict:
    if not sentences:
        return {}
    n = len(sentences)
    taigen = 0
    style = {k: 0 for k in COMMON_ENDINGS}
    for s in sentences:
        tail = s.rstrip("「」『』　 ")
        for k, pat in COMMON_ENDINGS.items():
            if pat.search(tail + "。"):
                style[k] += 1
                break
        if TAIGEN_DOME.search(s.rstrip("「」『』　 ")):
            taigen += 1
    rates = {k: round(v / n, 4) for k, v in style.items()}
    rates["taigen_dome"] = round(taigen / n, 4)
    return rates


def subject_omission_rate(sentences: list[str], tokenizer: Tokenizer) -> dict:
    """
    ヒューリスティック：文頭〜最初の述語までに主語マーカー（〜は／〜が）と
    その直前が名詞／代名詞になっている割合を「主語明示率」とし、1 から引いたものを省略率とする。
    fugashi があれば品詞情報を使い、無ければ近似する。絶対値ではなく相対比較用。
    """
    if not sentences:
        return {"rate": 0.0, "method": "no-data"}
    explicit = 0
    total = 0
    for s in sentences:
        if len(s) < 4:
            continue
        total += 1
        # 「は」「が」の位置を見る（最初の 20 字以内）
        m = re.search(r"(.{0,20}?)([はが])", s)
        if not m:
            continue
        prefix = m.group(1)
        if not prefix:
            continue
        if tokenizer.tagger is not None:
            toks = tokenizer.tokenize(prefix)
            if toks and toks[-1][1] in ("名詞", "代名詞", "固有名詞"):
                explicit += 1
        else:
            # 正規表現：末尾が漢字 / カタカナ / 代表的代名詞なら主語とみなす
            if KANJI.search(prefix[-1]) or KATAKANA.search(prefix[-1]) or \
               prefix.endswith(tuple(FIRST_PERSON)):
                explicit += 1
    if total == 0:
        return {"rate": 0.0, "method": "no-data"}
    explicit_rate = explicit / total
    return {
        "rate": round(1 - explicit_rate, 4),
        "explicit_rate": round(explicit_rate, 4),
        "sampled_sentences": total,
        "method": "heuristic (not dependency-parsed)",
    }


def paragraph_opening_conjunctions(paragraphs: list[str], top: int = 20) -> list[list]:
    c: Counter[str] = Counter()
    conjunctions = [
        "しかし", "けれども", "だが", "ところが", "そして", "また", "さらに",
        "しかも", "そのうえ", "それに", "だから", "それで", "したがって",
        "ゆえに", "つまり", "すなわち", "なぜなら", "もっとも", "ただし",
        "一方", "他方", "なお", "さて", "ところで", "では", "でも",
    ]
    for p in paragraphs:
        head = p.lstrip("　 \u3000")[:6]
        for conj in conjunctions:
            if head.startswith(conj):
                c[conj] += 1
                break
    return [[t, n] for t, n in c.most_common(top)]


# -------- L3 音韻・表記 --------

def char_ratio(text: str) -> dict:
    total = len(text)
    if total == 0:
        return {}
    kanji = len(KANJI.findall(text))
    hira = len(HIRAGANA.findall(text))
    kata = len(KATAKANA.findall(text))
    latin = len(LATIN.findall(text))
    digit = len(DIGIT.findall(text))
    other = total - (kanji + hira + kata + latin + digit)
    return {
        "total_chars": total,
        "kanji": round(kanji / total, 4),
        "hiragana": round(hira / total, 4),
        "katakana": round(kata / total, 4),
        "latin": round(latin / total, 4),
        "digit": round(digit / total, 4),
        "other": round(other / total, 4),
    }


def punctuation_density(text: str) -> dict:
    total = len(text)
    if total == 0:
        return {}
    density = {}
    for ch in PUNCT_CHARS:
        n = text.count(ch)
        if n:
            density[ch] = round(n / total * 1000, 3)
    return dict(sorted(density.items(), key=lambda x: x[1], reverse=True))


def paragraph_length_stats(paragraphs: list[str]) -> dict:
    if not paragraphs:
        return {}
    lens = sorted(len(p) for p in paragraphs if p.strip())
    if not lens:
        return {}
    n = len(lens)
    mean = sum(lens) / n
    median = lens[n // 2] if n % 2 else (lens[n // 2 - 1] + lens[n // 2]) / 2
    var = sum((L - mean) ** 2 for L in lens) / n
    return {
        "mean": round(mean, 2),
        "median": median,
        "std": round(math.sqrt(var), 2),
        "count": n,
    }


# -------- 集計 --------

def analyze(texts: list[tuple[Path, str]], tokenizer: Tokenizer) -> dict:
    all_text = "\n".join(t for _, t in texts)
    sentences = split_sentences(all_text)
    paragraphs: list[str] = []
    for _, t in texts:
        paragraphs.extend(p for p in t.split("\n\n") if p.strip())

    # tfidf 用：ファイル単位で tokenize した surface list
    docs: list[list[str]] = []
    for _, t in texts:
        toks = tokenizer.tokenize(t)
        docs.append([s for s, _ in toks if len(s) >= 2 and not PUNCT_PATTERN.search(s)])

    fp = count_first_person(all_text)
    fp_total = sum(fp.values()) or 1
    fp_ratio = {k: round(v / fp_total, 4) for k, v in sorted(
        fp.items(), key=lambda x: x[1], reverse=True) if v}

    meta = {
        "tokenizer": tokenizer.name,
        "total_chars": len(all_text),
        "total_sentences": len(sentences),
        "total_paragraphs": len(paragraphs),
        "source_files": len(texts),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "meta": meta,
        "L1_lexicon": {
            "first_person_pronouns": {
                "counts": fp,
                "ratios_among_first_person": fp_ratio,
            },
            "sentence_final_particles": count_sentence_final_particles(sentences),
            "onomatopoeia_candidates": [
                {"term": t, "count": c}
                for t, c in onomatopoeia_candidates(all_text, 30)
            ],
            "top_tfidf_terms": top_terms_tfidf(docs, 100),
        },
        "L2_syntax": {
            "sentence_length": sentence_length_stats(sentences),
            "ending_styles": ending_style_rates(sentences),
            "subject_omission": subject_omission_rate(sentences, tokenizer),
            "paragraph_opening_conjunctions": paragraph_opening_conjunctions(paragraphs, 20),
        },
        "L3_phonology": {
            "char_ratio": char_ratio(all_text),
            "punctuation_density_per_1000_chars": punctuation_density(all_text),
            "paragraph_length": paragraph_length_stats(paragraphs),
        },
        "limitations": {
            "tokenizer": tokenizer.name,
            "subject_omission_method": "heuristic (not dependency-parsed)",
            "known_inaccuracies": [
                "複文の従属節は未区別",
                "倒置文で主語判定が緩い",
                "会話中の主語省略も本文扱い",
                "終助詞検出は文末の単純一致のみ（複合終助詞は未対応）",
                "オノマトペ検出はカタカナ連続とひらがな反復の近似",
                "TF-IDF は同一作家コーパス内での相対比較向け、絶対値ではない",
            ],
            "use_as": "同一作家の時期間比較または他作家との相対差分。絶対値での引用は避ける",
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="L1-L3 文体統計を JSON で算出")
    p.add_argument("input", type=Path, help="入力ディレクトリまたはファイル（*.txt を再帰走査）")
    p.add_argument("--out", type=Path, default=None, help="出力 JSON ファイル")
    p.add_argument("--tokenizer", choices=["auto", "fugashi", "regex"], default="auto",
                   help="トークナイザ。auto は fugashi 優先、失敗時 regex")
    p.add_argument("--strict", action="store_true",
                   help="fugashi が使えない場合に exit 1 で落ちる")
    args = p.parse_args()

    src: Path = args.input.resolve()
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr)
        return 1

    texts = collect_texts(src)
    if not texts:
        print(f"warn: no .txt files under {src}", file=sys.stderr)
        return 0

    try:
        tokenizer = Tokenizer(args.tokenizer)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.strict and tokenizer.name != "fugashi":
        print("error: --strict 指定だが fugashi が使えない", file=sys.stderr)
        return 1

    result = analyze(texts, tokenizer)

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
        print(f"wrote {args.out} ({len(payload):,} bytes)", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
