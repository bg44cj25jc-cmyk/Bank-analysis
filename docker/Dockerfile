# One image, two roles. The API and the worker run the same code and differ only
# in the command, which keeps them impossible to skew apart at deploy time.
#
# The heavy dependencies -- Tesseract, Poppler, OpenCV -- are only used by the
# worker, but they cost about 200MB and splitting the image would mean building,
# tagging and version-matching two of them for one small firm. One image is the
# cheaper mistake.
FROM python:3.11-slim-bookworm

# The recogniser version is ASSERTED, not pinned to an exact Debian revision.
#
# It has to be held still: the measured 150 DPI baseline moves between Tesseract
# versions -- 37.8% row agreement when the fixtures were first read, 45.5% on
# 5.3.4 -- so an engine that drifts would silently re-baseline the very figures
# that decide whether a rescan actually helped.
#
# But pinning `tesseract-ocr=5.3.0-2` hard-codes a revision string that Debian
# withdraws on every security update, and the build starts failing for a reason
# that has nothing to do with accuracy. Asserting the major.minor instead holds
# what actually matters and fails loudly -- at build time, with the version
# printed -- if the base image ever moves underneath us.
ARG TESSERACT_SERIES=5.3

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SB_DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && installed="$(tesseract --version 2>&1 | head -1 | awk '{print $2}')" \
    && echo "tesseract ${installed}" \
    && case "${installed}" in \
         "${TESSERACT_SERIES}".*) : ;; \
         *) echo "FATAL: expected tesseract ${TESSERACT_SERIES}.x, got ${installed}." >&2; \
            echo "Re-benchmark the fixtures before changing TESSERACT_SERIES." >&2; \
            exit 1 ;; \
       esac

WORKDIR /app

# Dependencies first, so a source change does not re-resolve the wheel set.
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[api]"

# Nothing here runs as root: the data directory is a mounted DSM share holding
# client bank statements.
RUN useradd --create-home --uid 1000 statementbridge \
    && mkdir -p /data && chown -R statementbridge:statementbridge /data /app
USER statementbridge

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "statementbridge.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
