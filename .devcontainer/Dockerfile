# Shared image for all GardenPilot devcontainer configs. ESPHome is NOT installed here: `script/setup`
# installs the version pinned in uv.lock. Dependabot (.github/dependabot.yml) proposes tag + digest bumps.
# Python minor must equal .python-version.
# uv comes from a named stage because Dependabot does not see COPY --from with an image name; the stage must be first.
FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uv
FROM mcr.microsoft.com/devcontainers/python:3.14-trixie@sha256:3b3c45535947751e9dfcd513ef5bee858d221844f55e278e92d1cd8f5b1f2972

# uv, pinned by version (docs.astral.sh/uv/guides/integration/docker).
COPY --from=uv /uv /uvx /bin/

# libsdl2-dev: SDL2 headers/libs for the ESPHome `host` + `display: sdl` builds (script/sdl-smoke, later harness).
# build-essential, pkg-config: C/C++ toolchain for host builds and native Python wheels.
# git: PlatformIO/ESP-IDF fetch components and tools with git.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libsdl2-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Pre-create the cache mount points owned by `vscode`, so named volumes copy up the right owner.
# ~/.cache: ESP-IDF (native toolchain, ESPHome 2026.7+) and the uv cache; ~/.platformio: PlatformIO (older ESPHome, host).
# ~/.vscode-server/extensions: VS Code extensions survive container rebuilds.
# ~/.claude: optional Claude Code state (inert unless the extension is enabled).
RUN install -d -o vscode -g vscode /home/vscode/.cache /home/vscode/.platformio /home/vscode/.claude \
    /home/vscode/.vscode-server /home/vscode/.vscode-server/extensions

# Serial ports (/dev/ttyUSB*, /dev/ttyACM*) are group `dialout` on most distros.
RUN usermod -aG dialout vscode
