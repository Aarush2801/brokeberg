# One image for every Brokeberg Lambda; each function picks its handler via CMD (set in CDK).
# Build context is the repo root, narrowed by /.dockerignore to pipeline/ code + lockfile only.
# 3.12, not 3.11: the 3.11 image is Amazon Linux 2 (glibc 2.26), too old for psycopg arm64 wheels.
FROM public.ecr.aws/lambda/python:3.12

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

# Runtime deps only: no dev group, no `local` group (sentence-transformers/torch; prod uses Titan).
COPY pipeline/pyproject.toml pipeline/uv.lock /tmp/build/
RUN cd /tmp/build \
    && uv export --frozen --no-default-groups --no-emit-project --format requirements-txt \
        > requirements.txt \
    && uv pip install --no-cache --target "${LAMBDA_TASK_ROOT}" -r requirements.txt \
    && rm -rf /tmp/build

COPY pipeline/brokeberg ${LAMBDA_TASK_ROOT}/brokeberg

CMD ["brokeberg.aws.handlers.ingest"]
