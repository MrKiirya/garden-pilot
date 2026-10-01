# GardenPilot

[English version](README.md)

Контроллер для дачного участка на ESPHome: полив грядок в теплице и газона, обогрев грядок, датчики почвы и
воздуха, сенсорный экран 320×240 (LVGL) и полная интеграция с Home Assistant через нативный API ESPHome.
Сделан так, чтобы его можно было повторить: функции — это пакеты, которые включаются раскомментированием строки.

> **Статус:** в разработке, пока не готов к использованию. Сейчас: прототип на ESP32-S3 с сенсорным экраном
> ILI9341, три клапана грядок в теплице на контроллере `sprinkler` из ESPHome, датчики влажности почвы и воздуха.
> Планы и открытые вопросы: [docs/SPEC.md](docs/SPEC.md) (на английском).

## Быстрый старт (разработка)
Нужен [uv](https://docs.astral.sh/uv/getting-started/installation/) (devcontainer в планах).

```sh
script/setup                          # ставит закреплённую версию ESPHome, pytest, yamllint
cp secrets.example.yaml secrets.yaml  # и впишите свои Wi-Fi, ключ API и пароль OTA
script/lint                           # yamllint + esphome config
script/test                           # проверки репозитория
uv run esphome run garden-pilot.yaml  # сборка и прошивка (первый раз по USB, дальше по воздуху)
```

## Репозиторий
- `garden-pilot.yaml` — входной файл устройства: список пакетов.
- `packages/` — сеть, экран и тач, страницы LVGL, теплица (полив, датчики).
- `design/` — дизайн-система: правила, токены цветов и шрифтов, иконки.
- `docs/SPEC.md` — спецификация, архитектура, roadmap.
- `CLAUDE.md`, `.claude/`, `tasks/` — как проект разрабатывается с агентами Claude Code.

## Лицензия
[MIT](LICENSE)
