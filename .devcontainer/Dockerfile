# Shared image for all GardenPilot devcontainer configs. ESPHome is NOT installed here: `script/setup`
# installs the version pinned in uv.lock. Bump the tag + digest manually (see README) until Dependabot (task 003).
# Python minor must equal .python-version.
FROM mcr.microsoft.com/devcontainers/python:3-3.13-trixie@sha256:40c2785f2feb72a83bdf40bf052e1141d52b24bec60d4d5652eb27572d8df6b2

# uv, pinned by version (docs.astral.sh/uv/guides/integration/docker).
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /uvx /bin/

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
