#!/usr/bin/env python3
"""
5 カテゴリ（聲・眼・骨・魂・界）の蒸留結果をまとめ、
Phase 1.5 / Phase 2.5 の検査点で表示するサマリー表を生成する。
references/research/ 配下の 01-voice.md 〜 05-boundary.md を走査し、
各カテゴリの情報源数・一次／二次占比・主要発見を算出する。

使い方:
    python3 merge_research.py <skill ディレクトリのパス>

例:
    python3 merge_research.py examples/太宰治-skill

出力: サマリー表を markdown 形式で標準出力に印字
"""

import sys
import re
from pathlib import Path

CATEGORIES = {
    '01-voice':    '聲（Voice）',
    '02-eye':      '眼（Eye）',
    '03-bones':    '骨（Bones）',
    '04-soul':     '魂（Soul）',
    '05-boundary': '界（Boundary）',
}


def count_sources(content: str) -> dict:
    """情報源数と一次／二次占比を数える"""
    urls = re.findall(r'https?://[^\s\)]+', content)

    # 一次／二次マーカーを検出
    primary_markers = len(re.findall(r'一次|primary|本人|原文|作品集|原典', content, re.IGNORECASE))
    secondary_markers = len(re.findall(r'二次|secondary|転述|評論|書評', content, re.IGNORECASE))

    return {
        'url_count': len(urls),
        'unique_urls': len(set(urls)),
        'primary_markers': primary_markers,
        'secondary_markers': secondary_markers,
    }


def extract_key_findings(content: str, max_items: int = 3) -> list[str]:
    """主要発見を抽出（## 見出しまたは太字項を優先）"""
    headings = re.findall(r'^##\s+(.+)$', content, re.MULTILINE)
    if headings:
        return headings[:max_items]

    bolds = re.findall(r'\*\*(.+?)\*\*', content)
    if bolds:
        return bolds[:max_items]

    lines = [l.strip() for l in content.split('\n') if l.strip() and not l.startswith('#')]
    return [l[:50] + '...' if len(l) > 50 else l for l in lines[:max_items]]


def find_contradictions(files: dict[str, str]) -> list[str]:
    """ファイル間の矛盾をシンプルに検出する"""
    contradictions = []
    for name, content in files.items():
        matches = re.findall(r'(?:矛盾|相反|しかし実際は|とはいえ.*?異なる|争議).{0,100}', content)
        for m in matches:
            contradictions.append(f"{CATEGORIES.get(name, name)}: {m[:80]}")
    return contradictions[:5]


def main():
    if len(sys.argv) < 2:
        print("使い方: python3 merge_research.py <skill ディレクトリのパス>")
        sys.exit(1)

    skill_dir = Path(sys.argv[1])
    research_dir = skill_dir / 'references' / 'research'

    if not research_dir.exists():
        print(f"❌ ディレクトリが存在しません: {research_dir}")
        sys.exit(1)

    files = {}
    rows = []
    total_sources = 0
    total_primary = 0
    total_secondary = 0
    missing = []

    for key, label in CATEGORIES.items():
        md_file = research_dir / f"{key}.md"
        if not md_file.exists():
            missing.append(label)
            rows.append(f"│ {label:<14} │ {'❌ 欠落':<10} │ {'—':<26} │")
            continue

        content = md_file.read_text(encoding='utf-8')
        files[key] = content
        stats = count_sources(content)
        findings = extract_key_findings(content)

        total_sources += stats['unique_urls']
        total_primary += stats['primary_markers']
        total_secondary += stats['secondary_markers']

        findings_str = ', '.join(findings) if findings else '—'
        if len(findings_str) > 40:
            findings_str = findings_str[:37] + '...'

        rows.append(f"│ {label:<14} │ {stats['unique_urls']:<10} │ {findings_str:<26} │")

    contradictions = find_contradictions(files)

    print("┌────────────────┬────────────┬────────────────────────────┐")
    print("│ カテゴリ         │ 情報源数     │ 主要発見                    │")
    print("├────────────────┼────────────┼────────────────────────────┤")
    for row in rows:
        print(row)
    print("├────────────────┼────────────┼────────────────────────────┤")

    primary_ratio = f"{total_primary}/{total_primary + total_secondary}" if (total_primary + total_secondary) > 0 else "未標記"
    print(f"│ 総情報源数      │ {total_sources:<10} │ 一次占比: {primary_ratio:<16} │")

    if contradictions:
        print(f"│ 矛盾点          │ {len(contradictions)}箇所     │ {contradictions[0][:26]:<26} │")
    else:
        print(f"│ 矛盾点          │ 0 箇所     │ {'—':<26} │")

    if missing:
        print(f"│ 情報不足カテゴリ │ {len(missing)}個       │ {', '.join(missing):<26} │")
    else:
        print(f"│ 情報不足カテゴリ │ なし       │ {'—':<26} │")

    print("└────────────────┴────────────┴────────────────────────────┘")

    # 総括
    if total_sources < 10:
        print("\n⚠️ 情報源数が 10 未満です。期待値を下げるか補足調査を検討してください")
    if missing:
        print(f"\n⚠️ 欠落カテゴリ: {', '.join(missing)}。補足するか誠実境界（L14）で明記してください")


if __name__ == '__main__':
    main()
