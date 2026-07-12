FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="pitch-rti-toolkit"
LABEL org.opencontainers.image.vendor="Pitch Technologies"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxi6 libxtst6 xvfb xdotool \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY pyproject.toml README.md ./
COPY src ./src
COPY pitch ./pitch

RUN python -m pip install --no-cache-dir .

ENV PITCH_ASSET_ROOT=/workspace/pitch
ENV PITCH_USER_DATA_ROOT=/var/lib/pitch/data
ENV PITCH_INSTALLER_DROP_ROOT=/var/lib/pitch/installers
ENV PITCH_PREFLIGHT_ARTIFACT_ROOT=/var/lib/pitch/data/preflight

ENTRYPOINT ["pitch"]
