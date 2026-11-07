#!/usr/bin/env python3
"""
Обновление классов Discord в CSS темы.

Discord называет классы как <имя>_<хеш из 6 символов>, где хеш общий для всех классов
одного CSS-модуля. Когда Discord пересобирается, хеши меняются, а имена — почти никогда.
Скрипт:
  1. качает актуальные стили Discord (все CSS-чанки, включая ленивые) и собирает список живых классов;
  2. для каждого мёртвого класса темы ищет замену:
     а) по модулю: какие хеши стали какими — по общему списку замен сообщества
        (SyndiShanX/Update-Classes) и по совпадению имён внутри модулей;
     б) проверяет, что новый класс реально существует в Discord;
  3. печатает отчёт или (с --apply) переписывает файлы.

  python3 tools/classmap.py                 отчёт по файлам src/**/*.css и OldCord.theme.css
  python3 tools/classmap.py --apply         заменить найденное прямо в файлах
  python3 tools/classmap.py --mine          только классы в строках, которые ты добавил/изменил
                                            относительно оригинала (git diff с upstream/main)
  python3 tools/classmap.py --json out.json отчёт в JSON (для Action)
"""
import argparse, collections, concurrent.futures as cf, glob, json, os, re, subprocess, sys, urllib.request

DISCORD = "https://discord.com"
COMMUNITY = "https://raw.githubusercontent.com/SyndiShanX/Update-Classes/main/Changes.txt"
UA = {"User-Agent": "oldcord-classmap/1.0"}
CLASS_RE = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_-]{6})(?![\w-])")
SEL_RE = re.compile(r"\.([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_-]{6})(?![\w-])")


def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def split(c):
    # name_hash: последние 6 символов — хеш, перед ними разделитель "_"
    return c[:-7], c[-6:]


def live_classes(cache_dir=None):
    """Все классы, которые реально есть в стилях Discord прямо сейчас."""
    html = get(DISCORD + "/app")
    assets = set(re.findall(r'/assets/[^"\']+\.(?:css|js)', html))
    js = [a for a in assets if a.endswith(".js") and "/web." in a]
    css = {a for a in assets if a.endswith(".css")}
    # ленивые CSS-чанки перечислены в загрузчике webpack: if(ID===e)return""+e+".HASH.css"
    for a in js:
        src = get(DISCORD + a)
        for cid, h in re.findall(r'if\((\d+)===e\)return""\+e\+"\.([0-9a-f]{16})\.css"', src):
            css.add(f"/assets/{cid}.{h}.css")
        # и общий словарь: return""+({ID:"HASH",...})[e]+".css"  ->  /assets/HASH.css
        end = src.find('})[e]+".css"')
        if end != -1:
            start = src.rfind("({", 0, end)
            for h in re.findall(r'\d+:"([0-9a-f]{16})"', src[start:end]):
                css.add(f"/assets/{h}.css")
    if not css:
        sys.exit("Не нашёл стили Discord — формат страницы поменялся, скрипт надо обновить.")
    live = set()
    with cf.ThreadPoolExecutor(16) as ex:
        for text in ex.map(lambda a: get(DISCORD + a), sorted(css)):
            live.update(SEL_RE.findall(text))
    return live, len(css)


def community_pairs():
    try:
        lines = get(COMMUNITY, timeout=120).split("\n")
    except Exception as e:
        print(f"[!] Список сообщества недоступен ({e}), работаю без него", file=sys.stderr)
        return {}
    pairs = {}
    for i in range(0, len(lines) - 1, 2):
        a, b = lines[i].strip(), lines[i + 1].strip()
        if a and b and a != b:
            pairs[a] = b
    return pairs


def build_resolver(live, pairs, theme_classes):
    live_by_hash = collections.defaultdict(set)   # новый хеш -> имена
    live_by_name = collections.defaultdict(set)   # имя -> новые хеши
    for c in live:
        n, h = split(c)
        live_by_hash[h].add(n)
        live_by_name[n].add(h)

    # 1) голоса "старый хеш -> новый хеш" из списка сообщества (только если новый класс живой)
    votes = collections.defaultdict(collections.Counter)
    for old, new in pairs.items():
        if CLASS_RE.fullmatch(old) and new in live:
            on, oh = split(old)
            nn, nh = split(new)
            if on == nn:
                votes[oh][nh] += 1

    # 2) по совпадению имён: какие имена темы жили в старом модуле -> какой живой модуль содержит их все
    theme_by_hash = collections.defaultdict(set)
    for c in theme_classes:
        n, h = split(c)
        theme_by_hash[h].add(n)
    for oh, names in theme_by_hash.items():
        cand = None
        for n in names:
            hs = live_by_name.get(n, set())
            cand = set(hs) if cand is None else cand & hs
        # однозначно, и подтверждено хотя бы двумя именами (одно имя вроде "button" есть в сотне модулей)
        if cand and len(cand) == 1 and len(names) >= 2:
            votes[oh][next(iter(cand))] += len(names)

    hash_map = {oh: c.most_common(1)[0][0] for oh, c in votes.items()}

    def resolve(c):
        if c in live:
            return c, "ok"
        n, h = split(c)
        if h in hash_map and h != hash_map[h] and n in live_by_hash[hash_map[h]]:
            return f"{n}_{hash_map[h]}", "module"
        new = pairs.get(c)
        for _ in range(10):            # цепочки a -> b -> c
            if new is None or new in live:
                break
            new = pairs.get(new)
        if new and new in live:
            return new, "community"
        hs = live_by_name.get(n, set())
        if len(hs) == 1:               # имя уникально во всём Discord — угадываем, но помечаем
            return f"{n}_{next(iter(hs))}", "guess"
        return None, "dead"

    return resolve


def my_lines(root, base, files):
    """Номера строк (в текущих файлах), которые изменены относительно base."""
    git = ["git", "-C", root]
    mb = subprocess.check_output(git + ["merge-base", "HEAD", base], text=True).strip()
    res = {}
    for f in files:
        d = subprocess.check_output(git + ["diff", "-U0", mb, "--", os.path.relpath(f, root)], text=True)
        nums = set()
        for start, cnt in re.findall(r"^@@ -\S+ \+(\d+)(?:,(\d+))? @@", d, re.M):
            start, cnt = int(start), int(cnt or 1)
            nums.update(range(start, start + cnt))
        if nums:
            res[f] = nums
    return res


def theme_files(root):
    files = sorted(glob.glob(os.path.join(root, "src", "**", "*.css"), recursive=True))
    t = os.path.join(root, "OldCord.theme.css")
    return files + ([t] if os.path.exists(t) else [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="переписать файлы")
    ap.add_argument("--no-guess", action="store_true", help="не применять угаданные по уникальному имени замены")
    ap.add_argument("--mine", nargs="?", const="upstream/main", metavar="BASE",
                    help="только твои строки: изменённые относительно BASE (по умолчанию upstream/main)")
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--summary", metavar="FILE", help="дописать отчёт в markdown (для сводки GitHub Actions)")
    ap.add_argument("--fail-on-dead", action="store_true", help="код выхода 4, если остались ненайденные классы")
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    a = ap.parse_args()

    files = theme_files(a.root)
    texts = {f: open(f, encoding="utf-8", newline="").read() for f in files}

    mine = my_lines(a.root, a.mine, files) if a.mine else None

    def lines_of(f, t):
        ls = t.splitlines(keepends=True)
        return [l for i, l in enumerate(ls, 1) if mine is None or i in mine.get(f, ())]

    used = collections.defaultdict(set)
    for f, t in texts.items():
        for l in lines_of(f, t):
            for c in CLASS_RE.findall(l):
                used[c].add(os.path.relpath(f, a.root))

    print("Качаю стили Discord…", file=sys.stderr)
    try:
        live, ncss = live_classes()
    except Exception as e:
        print(f"[!] Не удалось скачать стили Discord: {e}", file=sys.stderr)
        return 5
    print(f"  {ncss} файлов стилей, {len(live)} живых классов", file=sys.stderr)
    pairs = community_pairs()
    print(f"  список сообщества: {len(pairs)} пар", file=sys.stderr)

    resolve = build_resolver(live, pairs, used.keys())
    result = {c: resolve(c) for c in used}
    stat = collections.Counter(how for _, how in result.values())

    print(f"\nКлассов в теме: {len(used)}")
    for k, label in [("ok", "живые, менять не надо"), ("module", "заменены по модулю"),
                     ("community", "заменены по списку сообщества"), ("guess", "угаданы по имени" + (" (не применены)" if a.no_guess else "")),
                     ("dead", "не найдены — правь руками")]:
        print(f"  {label:32} {stat.get(k, 0)}")
    dead = sorted(c for c, (_, how) in result.items() if how == "dead")
    if dead:
        print("\nНе найдены (класс удалён или переименован в Discord):")
        for c in dead:
            print(f"  {c:45} {', '.join(sorted(used[c]))}")
    guesses = sorted((c, n) for c, (n, how) in result.items() if how == "guess")
    if guesses:
        print("\nУгаданные (проверь глазами):")
        for c, n in guesses:
            print(f"  {c:45} -> {n}")

    if a.json:
        json.dump({c: {"new": n, "how": how, "files": sorted(used[c])} for c, (n, how) in result.items()},
                  open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if a.apply:
        allowed = {"module", "community"} | (set() if a.no_guess else {"guess"})
        repl = {c: n for c, (n, how) in result.items() if how in allowed}
        rx = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(repl, key=len, reverse=True))) + r")(?![\w-])") if repl else None
        changed = 0
        for f, t in texts.items():
            if not rx:
                break
            if mine is not None:
                out = "".join(rx.sub(lambda m: repl[m.group(1)], l) if i in mine.get(f, ()) else l
                              for i, l in enumerate(t.splitlines(keepends=True), 1))
            else:
                out = rx.sub(lambda m: repl[m.group(1)], t)
            if out != t:
                open(f, "w", encoding="utf-8", newline="").write(out)
                changed += 1
        print(f"\nЗаменено {len(repl)} классов в {changed} файлах.")

    if a.summary:
        title = "Классы в твоих фиксах" if a.mine else "Классы Discord во всей теме"
        md = [f"### {title}", "", "| | |", "|---|---|"]
        for k, label in [("ok", "живые"), ("module", "заменены по модулю"), ("community", "по списку сообщества"),
                         ("guess", "угаданы" + (" (не применены)" if a.no_guess else "")), ("dead", "**не найдены**")]:
            md.append(f"| {label} | {stat.get(k, 0)} |")
        if dead:
            md += ["", "<details><summary>Не найдены</summary>", "", "```"]
            md += [f"{c}  ({', '.join(sorted(used[c]))})" for c in dead]
            md += ["```", "</details>"]
        with open(a.summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n\n")

    return 4 if (a.fail_on_dead and dead) else 0


if __name__ == "__main__":
    sys.exit(main())
