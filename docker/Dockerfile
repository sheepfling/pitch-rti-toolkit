FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="pitch-rti-toolkit"
LABEL org.opencontainers.image.vendor="Pitch Technologies"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libxi6 libxtst6 xvfb xdotool \
    && rm -rf /var/lib/apt/lists/*

ARG PITCH_CONTAINER_WORKDIR
ARG PITCH_CONTAINER_ASSET_ROOT
ARG PITCH_CONTAINER_USER_DATA_ROOT
ARG PITCH_CONTAINER_INSTALLER_DROP_ROOT
ARG PITCH_CONTAINER_PREFLIGHT_ARTIFACT_ROOT

WORKDIR ${PITCH_CONTAINER_WORKDIR}

COPY pyproject.toml README.md ./
COPY src ./src
COPY pitch ./pitch

RUN python -m pip install --no-cache-dir .

ENV PITCH_ASSET_ROOT=${PITCH_CONTAINER_ASSET_ROOT}
ENV PITCH_USER_DATA_ROOT=${PITCH_CONTAINER_USER_DATA_ROOT}
ENV PITCH_INSTALLER_DROP_ROOT=${PITCH_CONTAINER_INSTALLER_DROP_ROOT}
ENV PITCH_PREFLIGHT_ARTIFACT_ROOT=${PITCH_CONTAINER_PREFLIGHT_ARTIFACT_ROOT}

ENTRYPOINT ["pitch"]
