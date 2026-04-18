#!/usr/bin/env python3
"""
生成された作家 skill の SKILL.md が文豪の品質基準を通過するか自動チェックする。
14 層の記述、3 モード、誠実境界（L13-L14）の存在、L12 の倫理注記などを確認する。

使い方:
    python3 quality_check.py <SKILL.md のパス>

例:
    python3 quality_check.py examples/太宰治-skill/SKILL.md
"""

import sys
import re
from pathlib import Path


def check_14_layers(content: str) -> tuple[bool, str]:
    """L1-L14 の全 14 層が記述されているか確認"""
    found = []
    missing = []
    for i in range(1, 15):
        if re.search(rf'\bL{i}\b', content):
            found.append(i)
        else:
            missing.append(i)
    passed = len(missing) == 0
    if passed:
        return True, f"14 層すべて記述あり ✅"
    return False, f"欠落層 {len(missing)} 個: L{', L'.join(map(str, missing))} ❌"


def check_5_categories(content: str) -> tuple[bool, str]:
    """5 カテゴリ（聲・眼・骨・魂・界）の記述を確認"""
    categories = ['聲', '眼', '骨', '魂', '界']
    missing = [c for c in categories if c not in content]
    passed = len(missing) == 0
    if passed:
        return True, "5 カテゴリすべて記述あり ✅"
    return False, f"欠落カテゴリ: {', '.join(missing)} ❌"


def check_3_modes(content: str) -> tuple[bool, str]:
    """3 モード（書く・添削・対話）の起動規則を確認"""
    modes = ['書く', '添削', '対話']
    found = [m for m in modes if m in content]
    passed = len(found) == 3
    if passed:
        return True, "3 モードすべて定義あり ✅"
    return False, f"欠落モード: {', '.join(set(modes) - set(found))} ❌"


def check_l12_ethics(content: str) -> tuple[bool, str]:
    """L12 の倫理注記を確認"""
    has_disclaimer = bool(re.search(r'臨床的診断ではない|推定|公開情報から', content))
    if not has_disclaimer:
        return False, "L12 倫理注記なし ❌（「臨床的診断ではない」必須）"
    return True, "L12 倫理注記あり ✅"


def check_anti_patterns(content: str) -> tuple[bool, str]:
    """L13 反パターンが 5 項目以上あるか"""
    match = re.search(r'L13.*?(?=L14|\Z)', content, re.DOTALL)
    if not match:
        return False, "L13 セクションなし ❌"

    section = match.group(0)
    items = re.findall(r'^[-*]\s+', section, re.MULTILINE)
    count = len(items)
    passed = count >= 5
    return passed, f"L13 反パターン: {count} 項目 {'✅' if passed else '❌（5 項目以上推奨）'}"


def check_limits(content: str) -> tuple[bool, str]:
    """L14 限界が 3 項目以上あるか"""
    match = re.search(r'L14.*?(?=##\s|\Z)', content, re.DOTALL)
    if not match:
        return False, "L14 セクションなし ❌"

    section = match.group(0)
    items = re.findall(r'^[-*]\s+', section, re.MULTILINE)
    count = len(items)
    passed = count >= 3
    return passed, f"L14 限界: {count} 項目 {'✅' if passed else '❌（3 項目以上必要）'}"


def check_research_date(content: str) -> tuple[bool, str]:
    """調査日が記載されているか"""
    has_date = bool(re.search(r'調査日[:：]\s*\d{4}[-/]\d{2}[-/]\d{2}', content))
    return has_date, "調査日あり ✅" if has_date else "調査日なし ❌（YYYY-MM-DD 形式で必須）"


def check_identity_declaration(content: str) -> tuple[bool, str]:
    """「あなたは [作家名] です」宣言があるか（憑依の起点）"""
    has_declaration = bool(re.search(r'あなたは.+?です', content))
    if not has_declaration:
        return False, "「あなたは〜です」宣言なし ❌（憑依の起点）"
    return True, "憑依宣言あり ✅"


def check_first_person(content: str) -> tuple[bool, str]:
    """一人称で記述されているか（三人称の自己言及がないか）"""
    # 「[作家名]は〜」のような三人称自己言及を検出
    # 注：厳密ではなく警告レベル
    third_person_patterns = re.findall(r'(この作家は|本作家は|[作家名]は)', content)
    # 「一人称」「「我」「「私」」などの記述があればポジティブ
    has_first_person_rule = bool(re.search(r'一人称|自称代名詞', content))
    if has_first_person_rule:
        return True, "一人称規則あり ✅"
    return False, "一人称規則なし ❌（憑依には必須）"


def main():
    if len(sys.argv) < 2:
        print("使い方: python3 quality_check.py <SKILL.md のパス>")
        sys.exit(1)

    skill_path = Path(sys.argv[1])
    if not skill_path.exists():
        print(f"❌ ファイルが存在しません: {skill_path}")
        sys.exit(1)

    content = skill_path.read_text(encoding='utf-8')

    checks = [
        ("14 層記述", check_14_layers),
        ("5 カテゴリ", check_5_categories),
        ("3 モード", check_3_modes),
        ("L12 倫理注記", check_l12_ethics),
        ("L13 反パターン", check_anti_patterns),
        ("L14 限界", check_limits),
        ("調査日", check_research_date),
        ("憑依宣言", check_identity_declaration),
        ("一人称規則", check_first_person),
    ]

    print(f"品質チェック: {skill_path.name}")
    print("=" * 60)

    passed_count = 0
    total = len(checks)

    for name, check_fn in checks:
        passed, detail = check_fn(content)
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {name:<14} {status}  {detail}")
        if passed:
            passed_count += 1

    print("=" * 60)
    print(f"結果: {passed_count}/{total} 通過")

    if passed_count == total:
        print("🎉 全項目通過。交付可能。")
    elif passed_count >= total - 2:
        print("⚠️ 軽微な不通過あり。修正のうえ交付を推奨。")
    else:
        print("❌ 多数の不通過項目あり。Phase 2 に戻って再蒸留を推奨。")

    sys.exit(0 if passed_count == total else 1)


if __name__ == '__main__':
    main()
