# GardenPilot

[![CI](https://github.com/MrKiirya/garden-pilot/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/MrKiirya/garden-pilot/actions/workflows/ci.yml)

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
Эталонная среда: **devcontainer** (VS Code + расширение Dev Containers): Python 3.14, uv, версия ESPHome из
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

**Обновление базового образа или uv:** теги и digest в `.devcontainer/Dockerfile` предлагает обновлять Dependabot; после слияния такого PR пересоберите контейнер.

Лёгкий путь для конечных пользователей (ESPHome Device Builder + удалённые пакеты, без devcontainer) в планах.

## Запуск на ПК (эмулятор)
`script/sim` собирает и запускает `garden-pilot-sim.yaml`: те же экраны LVGL и пакеты полива, что и на устройстве, на
платформе ESPHome `host`, в окне SDL 320x240; мышь работает как сенсорный экран. Железо не нужно, эмулятор **полностью
работает без Home Assistant**: время берётся с ПК, RUN/STOP на грядке переключает симулированное реле (каждое
изменение пишется в лог как `SIM relay_N ON/OFF`) и обновляет экран. Значения датчиков симулируются: температура и
влажность воздуха, влажность почвы теплицы и почва каждой грядки задаются числами и показываются на Home и Greenhouse
как настоящие датчики.

- **Страница SIM:** кнопка `SIM` (справа вверху на каждой странице) открывает виртуальную плату: живые индикаторы реле
  1..3 (клапаны грядок 1..3), по одному ползунку на каждое симулируемое значение и переключатель **Sim auto drift**
  (по умолчанию OFF; при ON почва сохнет на 1 % в минуту и растёт на 1 % за 10 с, пока работает реле грядки).
- **Из терминала:** `script/sim-ctl` работает с запущенным эмулятором через нативный API (тот же путь, что у Home
  Assistant): `script/sim-ctl list`, `script/sim-ctl get greenhouse_soil_moisture`,
  `script/sim-ctl set "Sim soil moisture" 35`, `script/sim-ctl switch "Sim auto drift" on`. Опции `--host`,
  `--port` (6053), `--key`, `--timeout`; код выхода 1 значит, что эмулятор недоступен, 2 ошибка вызова или сущности.
  Запускайте в том же devcontainer или на ПК с опубликованным портом.

- **Где:** в конфигурации devcontainer с SDL (выше; rootless Podman, X11) или на настольном хосте с dev-файлами SDL2
  (`sdl2-config` должен существовать, даже для `esphome config`). Затем `script/sim`; Ctrl+C останавливает.
- **Безопасно:** сборка всегда идёт с `secrets.example.yaml`, никогда с вашим настоящим `secrets.yaml`. Ключ API
  `sim_api_encryption_key` публичный, это заглушка: любой, кто достанет порт 6053, может переключать симулированные
  реле (ничего физического). Никогда не прошивайте эту сборку.
- **Home Assistant (по желанию):** добавьте интеграцию ESPHome по IP этого ПК (например `192.168.x.x`), порт 6053,
  ключ `sim_api_encryption_key` из `secrets.example.yaml`. Появится отдельное устройство «GardenPilot Sim» (id
  получают префикс `gardenpilot_sim_`); на платформе host нет обнаружения через mDNS. Devcontainer с SDL публикует
  порт 6053 только на loopback ПК, этого хватает для HA на том же ПК. Для HA на другой машине задайте на хосте
  `GP_SIM_API_BIND=0.0.0.0` до **Rebuild Container** и разрешите TCP 6053 в файрволе хоста (firewalld в Fedora и
  Bazzite). Docker на Linux может вместо этого использовать `--network=host`.
- **Проверка конфига эмулятора вручную:** `script/config garden-pilot-sim.yaml` и `script/compile garden-pilot-sim.yaml`
  берут ваш настоящий `secrets.yaml`, если он есть; в нём нет ключа эмулятора, и команда падает с «Secret
  'sim_api_encryption_key' not defined». Используйте `GP_SECRETS=example` или добавьте публичный ключ-заглушку из
  `secrets.example.yaml` в `secrets.yaml` (`script/sim` всегда берёт файл-пример).
- Если порт 6053 уже занят (другой эмулятор или программа на этом ПК), сначала остановите её.
- Длительности запуска и прочие настройки хранятся в `.esphome/sim-prefs/`. Если окно не появилось, проверьте доступ к
  X11 (`xhost`, выше); раннер использует программный рендеринг (`SDL_RENDER_DRIVER=software`), чтобы контейнер без
  `/dev/dri` не зависал.

## CI
Каждый pull request и каждый push в `master` внутри образа devcontainer запускают `script/lint` и `script/test`
(задача `checks`) и настоящую сборку прошивки для ESP32 с закреплённой и с самой старой поддерживаемой версией
ESPHome (`compile (pinned)`, `compile (minimum)`; минимум задан как `esphome-minimum` в `pyproject.toml`).
Еженедельный canary собирает прошивку с новейшим стабильным ESPHome и открывает (или закрывает) issue
`canary-failure`. Dependabot предлагает обновления actions, Python-зависимостей (включая ESPHome) и образов
devcontainer. CI проверяет только Docker Engine на Linux в неинтерактивном режиме.

Воспроизвести локально: `script/lint`, `script/test`, `GP_SECRETS=example script/compile` и
`GP_ESPHOME=minimum GP_SECRETS=example script/compile` для самой старой поддерживаемой версии ESPHome.

## Репозиторий
- `garden-pilot.yaml` — входной файл устройства: список пакетов. `garden-pilot-sim.yaml` — те же пакеты для эмулятора на ПК.
- `hardware/` — профиль платы (пины, драйверы реле) и `sim.yaml` (эмулятор на ПК и проверка конфига без платы); `packages/` — ядро (API, OTA, сеть, время), экран и тач (устройство или окно SDL), страницы LVGL, теплица (полив, грядки, необязательный датчик влажности грядки, датчики). Одна грядка — один блок `!include` в основном файле; минимум 2 грядки, пока нет собственного движка полива (этап 7 дорожной карты).
- `design/` — дизайн-система: правила, токены цветов и шрифтов, иконки.
- `docs/SPEC.md` — спецификация, архитектура, roadmap.
- `CLAUDE.md`, `.claude/`, `tasks/` — как проект разрабатывается с агентами Claude Code.

## Лицензия
[MIT](LICENSE)

Шрифт Montserrat Bold в `packages/lvgl/fonts/` сторонний, под лицензией SIL Open Font License 1.1 (см. `packages/lvgl/fonts/OFL.txt`).
