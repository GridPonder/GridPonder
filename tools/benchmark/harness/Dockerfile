# Image for `--isolation docker`.
#
#   docker build -t gridponder-harness:latest tools/benchmark/harness
#
# What goes in here is what the agent gets. Nothing from this repo is copied in
# — not the packs, not the engine, not the solver — because the whole point of
# running in a container is that the host filesystem is absent by construction
# rather than by a list of paths we remembered to hide. The sandbox is mounted
# at run time and contains only RULES.md and ./play.
#
# Ubuntu rather than alpine: the Claude Code CLI ships a glibc binary.
FROM ubuntu:24.04

# ca-certificates for the API, python3 for the local baseline agent and for
# ./play, which is stdlib-only on purpose.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 \
 && rm -rf /var/lib/apt/lists/*

# Node is the CLI's installer, not its runtime — the published binary is
# self-contained — but installing through npm keeps the version pinnable.
ARG NODE_MAJOR=22
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

ARG CLAUDE_VERSION=latest
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
 && npm cache clean --force

# The agent runs as the invoking uid (isolation.py passes --user), which will
# not exist in /etc/passwd. Tools that look up the current user need to not
# fail on that; an nsswitch fallback is simpler than pre-creating every uid.
ENV npm_config_cache=/tmp/.npm \
    XDG_CACHE_HOME=/tmp/.cache

# No CMD: isolation.py always supplies the command to run.
