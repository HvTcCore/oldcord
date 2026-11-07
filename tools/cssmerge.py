#!/usr/bin/env python3
"""
Драйвер слияния CSS для git, который понимает переименование классов Discord.

Когда в оригинале массово меняют классы (.wrapper_cc5dd2 -> .wrapper_hqZPsU), а у тебя рядом
поменяны свойства, обычный git видит две правки впритык и выдаёт конфликт. Этот драйвер:
  1. сравнивает базу с новой версией оригинала и находит строки, которые отличаются только
     хешами классов -> собирает таблицу переименований;
  2. применяет те же переименования к базе и к твоей версии;
  3. делает обычное трёхстороннее слияние (git merge-file).
Настоящие конфликты (когда оба поменяли одно и то же по смыслу) остаются конфликтами.

Подключается из tools/sync.sh. Вызов: cssmerge.py BASE OURS THEIRS [PATH]
(OURS — оригинал с уже накатанными коммитами, THEIRS — твой коммит; результат пишется в OURS)
"""
import difflib, re, subprocess, sys

CLASS = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9]*)_([A-Za-z0-9_-]{6})(?![\w-])")


def norm(line):
    return CLASS.sub(lambda m: m.group(1) + "_", line).strip()


def renames(base, new):
    """Таблица старый класс -> новый класс по строкам, отличающимся только хешами."""
    a, b = base.splitlines(), new.splitlines()
    na, nb = [norm(x) for x in a], [norm(x) for x in b]
    votes = {}
    # выравниваем по нормализованным строкам: тогда переименованные строки попадают в "equal"
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, na, nb, autojunk=False).get_opcodes():
        if tag != "equal":
            continue
        for x, y in zip(a[i1:i2], b[j1:j2]):
            if x == y:
                continue
            tx, ty = CLASS.findall(x), CLASS.findall(y)
            if len(tx) != len(ty):
                continue
            for (n1, h1), (n2, h2) in zip(tx, ty):
                if n1 == n2 and h1 != h2:
                    votes.setdefault(f"{n1}_{h1}", {}).setdefault(f"{n2}_{h2}", 0)
                    votes[f"{n1}_{h1}"][f"{n2}_{h2}"] += 1
    # берём только однозначные переименования
    return {old: next(iter(v)) for old, v in votes.items() if len(v) == 1}


def apply(text, m):
    if not m:
        return text
    rx = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(m, key=len, reverse=True))) + r")(?![\w-])")
    return rx.sub(lambda x: m[x.group(1)], text)


def read(p):
    with open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write(p, t):
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(t)


def main():
    base_p, ours_p, theirs_p = sys.argv[1:4]
    path = sys.argv[4] if len(sys.argv) > 4 else "file"
    base, ours, theirs = read(base_p), read(ours_p), read(theirs_p)

    m = renames(base, ours)
    if m:
        write(base_p, apply(base, m))
        write(theirs_p, apply(theirs, m))

    r = subprocess.run(["git", "merge-file", "-L", "upstream", "-L", "base", "-L", "fixes",
                        ours_p, base_p, theirs_p])
    if m:
        print(f"cssmerge: {path}: учтено переименований классов: {len(m)}", file=sys.stderr)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
