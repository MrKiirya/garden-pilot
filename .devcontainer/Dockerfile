# Shared image for all GardenPilot devcontainer configs. ESPHome is NOT installed here: `script/setup`
# installs the version pinned in uv.lock. Dependabot (.github/dependabot.yml) proposes tag + digest bumps.
# Python minor must equal .python-version.
# uv comes from a named stage because Dependabot does not see COPY --from with an image name; the stage must be first.
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM mcr.microsoft.com/devcontainers/python:3.14-trixie@sha256:28835c112fd097cb6d2fe1e195b660d66ae051859070a9b871fa2308f35897d3

# uv, pinned by version (docs.astral.sh/uv/guides/integration/docker).
COPY --from=uv /uv /uvx /bin/

# libsdl2-dev: SDL2 headers/libs for the ESPHome `host` + `display: sdl` builds (script/sdl-smoke, later harness).
# build-essential, pkg-config: C/C++ toolchain for host builds and native Python wheels.
# xvfb, xdotool: headless screenshots and taps of the emulator for script/sim-ui.
# git: PlatformIO/ESP-IDF fetch components and tools with git.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libfaketime \
        libsdl2-dev \
        pkg-config \
        xdotool \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

# Pre-create the cache mount points owned by `vscode`, so named volumes copy up the right owner.
# ~/.cache: ESP-IDF (native toolchain, ESPHome 2026.7+) and the uv cache; ~/.platformio: PlatformIO (older ESPHome, host).
# ~/.vscode-server/extensions: VS Code extensions survive container rebuilds.
# ~/.claude: optional Claude Code state (inert unless the extension is enabled).
RUN install -d -o vscode -g vscode /home/vscode/.cache /home/vscode/.platformio /home/vscode/.claude \
    /home/vscode/.vscode-server /home/vscode/.vscode-server/extensions

# Serial ports (/dev/ttyUSB*, /dev/ttyACM*) are group `dialout` on most distros.
RUN usermod -aG dialout vscode
