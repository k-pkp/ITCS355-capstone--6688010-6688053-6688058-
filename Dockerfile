# The capstone's nightly job, as a container.
#
# Pinned by digest rather than by tag, for the reason Lab 5 demonstrated: the same tag was
# pushed three times in one afternoon while fixing a pipeline, and ended up naming a commit
# whose code was not inside the image. A digest is computed from the contents.
FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9 AS builder

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim@sha256:da047cb8f9d1d98e5c070f5300ba9f7274e33b8fc0e5be5ed88740aed1b95ba9

# A non-root user, so a container that is broken into cannot rewrite its own code.
RUN useradd --create-home --uid 10001 runner

COPY --from=builder /install /usr/local
WORKDIR /app

COPY --chown=runner:runner src/ ./src/
COPY --chown=runner:runner scripts/ ./scripts/
COPY --chown=runner:runner reports/bank-model.joblib ./reports/bank-model.joblib

# The record of which model bytes the gate approved. The job hashes the model above
# and refuses to score if it does not match this file.
COPY --chown=runner:runner reports/approved-model.json ./reports/approved-model.json

USER runner

# Credentials never enter an image layer. They arrive at runtime from the identity the job
# executes as.
ENTRYPOINT ["python", "scripts/score_nightly.py"]
