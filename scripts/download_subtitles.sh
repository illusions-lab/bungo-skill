#!/bin/bash
# YouTube 動画から字幕をダウンロードする
# 使い方: ./download_subtitles.sh <YouTube_URL> [出力ディレクトリ]
# 人工字幕を優先し、なければ自動生成字幕を取得する
# 言語優先順位: 日本語 > 英語 > 中国語 > その他
#
# 注記: このスクリプトは女娲時代の名残。文豪.skill では作品集中心のため使用頻度は低いが、
# 動画系の個人ブロガー・講演者を蒸留する場合には有用。

set -e

URL="$1"
OUTPUT_DIR="${2:-.}"

if [ -z "$URL" ]; then
    echo "使い方: ./download_subtitles.sh <YouTube_URL> [出力ディレクトリ]"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo ">>> 利用可能な字幕を確認中..."
yt-dlp --list-subs --no-download "$URL" 2>/dev/null | tail -20

echo ""
echo ">>> 人工字幕のダウンロードを試行（日本語優先）..."

# 試行1: 人工日本語字幕
if yt-dlp --write-subs --sub-langs "ja,ja-JP" --sub-format srt --skip-download -o "$OUTPUT_DIR/%(title)s" "$URL" 2>/dev/null; then
    FOUND=$(find "$OUTPUT_DIR" -name "*.srt" -newer /tmp/.ytdlp_marker 2>/dev/null | head -1)
    if [ -n "$FOUND" ]; then
        echo "✅ ダウンロード成功: $FOUND"
        exit 0
    fi
fi

# 試行2: 人工英語字幕
echo ">>> 日本語の人工字幕なし、英語を試行..."
if yt-dlp --write-subs --sub-langs "en,en-US,en-GB" --sub-format srt --skip-download -o "$OUTPUT_DIR/%(title)s" "$URL" 2>/dev/null; then
    FOUND=$(find "$OUTPUT_DIR" -name "*.srt" -mmin -1 2>/dev/null | head -1)
    if [ -n "$FOUND" ]; then
        echo "✅ ダウンロード成功: $FOUND"
        exit 0
    fi
fi

# 試行3: 自動生成字幕（日本語優先）
echo ">>> 人工字幕なし、自動生成字幕を試行..."
if yt-dlp --write-auto-subs --sub-langs "ja,en,zh-Hans" --sub-format srt --skip-download -o "$OUTPUT_DIR/%(title)s" "$URL" 2>/dev/null; then
    FOUND=$(find "$OUTPUT_DIR" -name "*.srt" -o -name "*.vtt" 2>/dev/null | head -1)
    if [ -n "$FOUND" ]; then
        echo "✅ 自動字幕のダウンロード成功: $FOUND"
        exit 0
    fi
fi

echo "❌ 利用可能な字幕が見つかりませんでした"
exit 1
