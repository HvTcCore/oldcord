#!/usr/bin/env bash
# OldCord FireFix — патчер: подтягивает апстрим, накатывает фиксы, собирает публикуемую ветку.
# Работает в Linux, macOS и Windows (Git Bash / tools\sync.cmd). Нужны только git и perl
# (perl идёт в комплекте с Git for Windows и есть в Linux/macOS).
#
#   tools/sync.sh            обновить локально (ничего не пушит)
#   tools/sync.sh --push     обновить и запушить fixes + main
#   tools/sync.sh --build    только пересобрать main из fixes (после ручных правок)
#
# Ветки:
#   fixes  — апстрим + ТВОИ коммиты с фиксами. Ссылки milbits НЕ трогаем. Править только тут.
#   main   — генерируется скриптом: fixes + автозамена ссылок и шапки. Руками не править.
#
# Коды выхода: 0 ок, 2 конфликт при rebase (нужно решить руками), 3 проверка не прошла.
set -euo pipefail

# ---------- настройки ----------
UPSTREAM_URL="https://github.com/milbits/oldcord"
UPSTREAM_BRANCH="main"
FIXES_BRANCH="fixes"
PUBLISH_BRANCH="main"
UP_USER="milbits"
MY_USER="hvtccore"
THEME_FILE="OldCord.theme.css"
NAME_SUFFIX=" [FireFix]"
VERSION_SUFFIX="-firefix"
DESC_SUFFIX=" [Partial fix for Firefox (InTest)]"
MARKER="SwFx"   # маркер твоих правок, по нему проверяем, что ничего не потерялось
# -------------------------------

MODE="local"
case "${1:-}" in
  --push)  MODE="push" ;;
  --build) MODE="build" ;;
  "") ;;
  *) echo "неизвестный аргумент: $1"; exit 1 ;;
esac

cd "$(git rev-parse --show-toplevel)"
say()  { echo "==> $*"; }
warn() { echo "[!] $*"; }

command -v perl >/dev/null || { echo "Не найден perl. На Windows запускай через Git Bash или tools\\sync.cmd."; exit 1; }

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Есть незакоммиченные изменения — закоммить или спрячь (git stash) их сначала."; exit 1
fi

count_markers() {
  local n=0 line
  while IFS= read -r line; do n=$((n + ${line##*:})); done \
    < <(git grep -c "$MARKER" "$1" -- src "$THEME_FILE" 2>/dev/null || true)
  echo "$n"
}

if [[ "$MODE" != "build" ]]; then
  git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "$UPSTREAM_URL"
  # rerere запоминает, как ты решил конфликт, и в следующий раз решает его сам
  git config rerere.enabled true
  git config rerere.autoupdate true

  say "Тяну апстрим"
  git fetch -q upstream "$UPSTREAM_BRANCH"
  NEW_UP="upstream/$UPSTREAM_BRANCH"

  git checkout -q "$FIXES_BRANCH"
  OLD_UP="$(git merge-base HEAD "$NEW_UP")"
  if [[ "$OLD_UP" == "$(git rev-parse "$NEW_UP")" ]]; then
    say "Новых коммитов в апстриме нет"
  else
    N="$(git rev-list --count "$OLD_UP..$NEW_UP")"
    say "В апстриме новых коммитов: $N, накатываю фиксы"
    BEFORE="$(count_markers HEAD)"
    FIX_FILES="$(git diff --name-only "$OLD_UP" HEAD)"

    if ! git rebase -q "$NEW_UP"; then
      echo
      warn "Конфликт. Это значит, что апстрим поменял те же строки, что и ты."
      echo "  1) git status — посмотри файлы с конфликтом, поправь их"
      echo "  2) git add <файл> && git rebase --continue"
      echo "  3) снова запусти sync с --push (или --build)"
      echo "  Передумал: git rebase --abort"
      exit 2
    fi

    AFTER="$(count_markers HEAD)"
    if [[ "$BEFORE" != "$AFTER" ]]; then
      warn "Число маркеров $MARKER изменилось: было $BEFORE, стало $AFTER. Проверь, не потерялся ли фикс."
    fi

    # Файлы с твоими фиксами, которые апстрим тоже менял: слилось чисто, но классы Discord
    # могли переименоваться и фикс мог перестать срабатывать — их стоит проверить в клиенте.
    TOUCHED="$(git diff --name-only "$OLD_UP" "$NEW_UP" -- $FIX_FILES || true)"
    if [[ -n "$TOUCHED" ]]; then
      say "Апстрим менял файлы, где есть твои фиксы (стоит проверить в клиенте):"
      git diff --stat "$OLD_UP" "$NEW_UP" -- $TOUCHED | sed 's/^/    /'
    fi
  fi
fi

# ---------- сборка публикуемой ветки ----------
say "Собираю $PUBLISH_BRANCH из $FIXES_BRANCH"
git checkout -q -B "$PUBLISH_BRANCH" "$FIXES_BRANCH"

export UP_USER MY_USER NAME_SUFFIX VERSION_SUFFIX DESC_SUFFIX

# Меняем только ссылки, а не имя автора (milbit остаётся в @author)
git ls-files -z -- '*.css' '*.md' | xargs -0 perl -i -pe '
  s#\Q$ENV{UP_USER}\E\.github\.io#$ENV{MY_USER}.github.io#g;
  s#github\.com/\Q$ENV{UP_USER}\E/oldcord#github.com/$ENV{MY_USER}/oldcord#gi;
  s#raw\.githubusercontent\.com/\Q$ENV{UP_USER}\E/oldcord#raw.githubusercontent.com/$ENV{MY_USER}/oldcord#gi;
'

# Шапка темы: берём значения апстрима и дописываем суффиксы (окончания строк сохраняем, в т.ч. CRLF)
perl -i -pe '
  if ($. <= 15) {
    s/^( \* \@name .*?)[ \t]*(\r?)$/$1$ENV{NAME_SUFFIX}$2/;
    s/^( \* \@version .*?)[ \t]*(\r?)$/$1$ENV{VERSION_SUFFIX}$2/;
    s/^( \* \@description .*?)[ \t]*(\r?)$/$1$ENV{DESC_SUFFIX}$2/;
  }
' "$THEME_FILE"

LEFT="$(git grep -nE "${UP_USER}\.github\.io|(github|githubusercontent)\.com/${UP_USER}/" -- '*.css' '*.md' || true)"
if [[ -n "$LEFT" ]]; then
  warn "Остались ссылки на апстрим (добавь шаблон замены выше):"
  echo "$LEFT"
  git checkout -q -f "$FIXES_BRANCH"
  exit 3
fi

UPVER="$(git log -1 --format=%h "upstream/$UPSTREAM_BRANCH" 2>/dev/null || echo '?')"
git commit -qam "auto: build from $FIXES_BRANCH (upstream $UPVER)"
say "Готово: $(git log -1 --format='%h %s')"
head -n 9 "$THEME_FILE" | sed 's/^/    /'

git checkout -q "$FIXES_BRANCH"

if [[ "$MODE" == "push" ]]; then
  git fetch -q origin "$PUBLISH_BRANCH" 2>/dev/null || true
  if git rev-parse -q --verify "origin/$PUBLISH_BRANCH" >/dev/null &&
     [[ "$(git rev-parse "$PUBLISH_BRANCH^{tree}")" == "$(git rev-parse "origin/$PUBLISH_BRANCH^{tree}")" ]]; then
    # Содержимое не изменилось — не пушим, чтобы GitHub Pages не пересобирался впустую
    git branch -q -f "$PUBLISH_BRANCH" "origin/$PUBLISH_BRANCH"
    say "Изменений нет, пушить нечего"
    exit 0
  fi
  say "Пушу (GitHub Pages обновится сам через пару минут)"
  git push -q --force-with-lease origin "$FIXES_BRANCH"
  git push -q --force origin "$PUBLISH_BRANCH"
else
  echo
  echo "Проверь и запушь:  git push --force-with-lease origin $FIXES_BRANCH && git push -f origin $PUBLISH_BRANCH"
fi
