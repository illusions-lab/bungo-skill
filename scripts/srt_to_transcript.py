#!/usr/bin/env python3
"""
SRT/VTT 字幕ファイルを純テキストの transcript に洗浄する。
タイムスタンプ・連番・重複行・HTML タグを除去し、可読性の高い文章を出力する。

使い方:
    python3 srt_to_transcript.py input.srt [output.txt]
    python3 srt_to_transcript.py input.vtt [output.txt]

出力ファイルを指定しない場合は input_transcript.txt として保存する。
"""

import sys
import re
from pathlib import Path


def clean_srt(content: str) -> str:
    """SRT 形式の字幕を洗浄する"""
    lines = content.strip().split('\n')
    texts = []

    for line in lines:
        line = line.strip()
        # 連番行（数字のみ）をスキップ
        if re.match(r'^\d+$', line):
            continue
        # タイムスタンプ行をスキップ
        if re.match(r'\d{2}:\d{2}:\d{2}', line):
            continue
        # 空行をスキップ
        if not line:
            continue
        # HTML タグを除去
        line = re.sub(r'<[^>]+>', '', line)
        # VTT の position マーカーを除去
        line = re.sub(r'align:.*$|position:.*$', '', line).strip()
        if line:
            texts.append(line)

    # 連続する重複行を除去（自動字幕でよく発生する）
    deduped = []
    for text in texts:
        if not deduped or text != deduped[-1]:
            deduped.append(text)

    # 段落に結合：短文を連結し、文末記号か長さで段落を区切る
    result = []
    current = []

    for text in deduped:
        current.append(text)
        joined = ' '.join(current)
        # 累積が 200 字を超える、または文末記号があれば段落を確定
        if len(joined) > 200 or re.search(r'[。！？.!?]$', text):
            result.append(joined)
            current = []

    if current:
        result.append(' '.join(current))

    return '\n\n'.join(result)


def clean_vtt(content: str) -> str:
    """VTT 形式の字幕を洗浄する（ヘッダ除去後は SRT ロジックで処理）"""
    # WEBVTT ヘッダを除去
    content = re.sub(r'^WEBVTT.*?\n\n', '', content, flags=re.DOTALL)
    # NOTE ブロックを除去
    content = re.sub(r'NOTE.*?\n\n', '', content, flags=re.DOTALL)
    return clean_srt(content)


def main():
    if len(sys.argv) < 2:
        print("使い方: python3 srt_to_transcript.py <input.srt|input.vtt> [output.txt]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"❌ ファイルが存在しません: {input_path}")
        sys.exit(1)

    # 出力ファイル名の既定値
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
    else:
        output_path = input_path.parent / f"{input_path.stem}_transcript.txt"

    # 読み込みと形式判定
    content = input_path.read_text(encoding='utf-8')

    if input_path.suffix.lower() == '.vtt' or content.startswith('WEBVTT'):
        transcript = clean_vtt(content)
    else:
        transcript = clean_srt(content)

    output_path.write_text(transcript, encoding='utf-8')

    # 統計出力
    char_count = len(transcript)
    paragraph_count = transcript.count('\n\n') + 1
    print(f"✅ 変換完了: {output_path}")
    print(f"   字数: {char_count}  段落数: {paragraph_count}")


if __name__ == '__main__':
    main()
