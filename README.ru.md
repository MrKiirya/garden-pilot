# GardenPilot

[English version](README.md)

Контроллер для дачного участка на ESPHome: полив грядок в теплице и газона, обогрев грядок, датчики почвы и
воздуха, сенсорный экран 320×240 (LVGL) и полная интеграция с Home Assistant через нативный API ESPHome.
Сделан так, чтобы его можно было повторить: функции — это пакеты, которые включаются раскомментированием строки.

> **Статус:** в разработке, пока не готов к использованию. Сейчас: прототип на ESP32-S3 с сенсорным экраном
> ILI9341, три клапана грядок в теплице на контроллере `sprinkler` из ESPHome, датчики влажности почвы и воздуха.
> Планы и открытые вопросы: [docs/SPEC.md](docs/SPEC.md) (на английском).

## Быстрый старт (разработка)
Нужен [uv](https://docs.astral.sh/uv/getting-started/installation/) (или используйте devcontainer ниже).

```sh
script/setup                          # ставит закреплённую версию ESPHome, pytest, yamllint
cp secrets.example.yaml secrets.yaml  # и впишите свои Wi-Fi, ключ API и пароль OTA
script/lint                           # yamllint + esphome config
script/test                           # проверки репозитория
uv run esphome run garden-pilot.yaml  # сборка и прошивка (первый раз по USB, дальше по воздуху)
```

## Среда разработки
Эталонная среда: **devcontainer** (VS Code + расширение Dev Containers): Python 3.13, uv, версия ESPHome из
`uv.lock`, SDL2, кэши ESP-IDF / PlatformIO в именованных томах. Обычный `uv` на хосте (см. «Быстрый старт») тоже
работает.

**Статус проверки:** автор проверил Linux с rootless Podman (SELinux enforcing) в VS Code, включая прошивку по USB
и OTA из контейнера. Windows (Docker Desktop + WSL2) пока не проверялся; Docker Engine на Linux и macOS не
проверялись (отчёты приветствуются). Поддерживается только обычная установка VS Code; для
Flatpak VS Code нужен обходной путь из апстрима для доступа к контейнерному движку хоста, в репозитории его нет.

1. Установите VS Code, расширение Dev Containers и Docker (Desktop, на Linux можно Engine) или Podman.
2. Откройте репозиторий, выполните **Dev Containers: Reopen in Container** и выберите конфиг:
   - **GardenPilot**: по умолчанию, работает везде, без монтирования дисплея хоста.
   - **GardenPilot + SDL window (Linux host)**: дополнительно монтирует сокет X11, чтобы `script/sdl-smoke` мог
     открыть окно. Если X-сервер отказывает в доступе, выполните на хосте `xhost +SI:localuser:$(id -un)`.
3. `script/setup` запускается сам. Дальше `script/lint`, `script/test`, `uv run esphome compile garden-pilot.yaml`.

**Windows:** клонируйте репозиторий внутри дистрибутива WSL2, откройте его из окна «WSL:», затем переоткройте в
контейнере. **macOS:** для SDL нужен XQuartz («Allow connections from network clients») и VS Code, запущенный с
заданной `DISPLAY`.

**Rootless Podman (Linux):** в пользовательских настройках VS Code задайте `dev.containers.dockerPath` = `podman`
и передайте VS Code переменную `PODMAN_USERNS=keep-id` (например, в `~/.config/environment.d/podman.conf`, затем
перезайдите в сессию), чтобы файлы, созданные в контейнере, принадлежали вам. Конфиги используют
`--security-opt label=disable`, чтобы SELinux не блокировал рабочую копию; цена: контейнер не изолирован метками.

**USB на Linux (по желанию).** UART-мост не всегда `ttyUSB`: CH340 и CP210x дают `/dev/ttyUSB*`, CH343 и CH9102 —
`/dev/ttyACM*` (cdc_acm). Определите порт через `ls -l /dev/serial/by-id/` (имя производителя моста против
«Espressif USB JTAG») и предпочитайте разъём UART-моста платы. При подключённой плате запустите VS Code из
терминала с переменными, например: `GP_SERIAL_DEVICE=/dev/ttyACM0 GP_SERIAL_GROUP=keep-groups code .`
(`keep-groups` для Podman, пользователь должен быть в `dialout`; для Docker укажите GID группы `dialout` хоста).
Без переменных контейнер стартует без serial-устройства. Если `GP_SERIAL_DEVICE` задана, а плата отключена,
создание контейнера завершится ошибкой, поэтому задавайте переменные только на время прошивки по USB. После первой
прошивки USB для OTA не нужен. Нативный USB-порт (Espressif USB JTAG) работает по мере возможности: порт пропадает
и появляется при сбросе, контейнер может держать устаревший узел. Тогда перезапустите контейнер или соберите в
контейнере и прошейте factory-образ с хоста.

**Прошивка на Windows / macOS:** контейнер не видит USB. Первый раз прошейте с хоста (путь к factory-образу печатает
`esphome compile`; используйте https://web.esphome.io в Chrome/Edge или esptool на хосте; в Windows usbipd-win
пробрасывает USB в WSL). Дальше загружайте по воздуху из контейнера **по IP**:
`uv run esphome upload garden-pilot.yaml --device <IP устройства>`. mDNS (`.local`) в контейнере часто не
резолвится, поэтому для OTA и логов используйте IP везде.

**По желанию: Claude Code.** В образ не входит. Чтобы расширение VS Code ставилось в каждый контейнер, добавьте в
пользовательские настройки `"dev.containers.defaultExtensions": ["anthropic.claude-code"]`; вход сохраняется между
пересборками в именованном томе. Установленное расширение остаётся в томе расширений, даже если убрать
настройку; чтобы удалить его, сбросьте этот том (см. ниже).

**Том расширений:** расширения VS Code Server лежат в именованном томе `garden-pilot-vscode-extensions`, чтобы не
ставиться заново при каждой пересборке. Если расширение сломалось, удалите контейнер и выполните
`podman volume rm garden-pilot-vscode-extensions` (`docker volume rm ...` для Docker), затем пересоберите.

**Обновление базового образа или uv:** правьте тег и digest в `.devcontainer/Dockerfile` (`skopeo inspect` или
`docker buildx imagetools inspect`) и версию uv отдельным PR.

Лёгкий путь для конечных пользователей (ESPHome Device Builder + удалённые пакеты, без devcontainer) в планах.

## Репозиторий
- `garden-pilot.yaml` — входной файл устройства: список пакетов.
- `packages/` — сеть, экран и тач, страницы LVGL, теплица (полив, датчики).
- `design/` — дизайн-система: правила, токены цветов и шрифтов, иконки.
- `docs/SPEC.md` — спецификация, архитектура, roadmap.
- `CLAUDE.md`, `.claude/`, `tasks/` — как проект разрабатывается с агентами Claude Code.

## Лицензия
[MIT](LICENSE)
