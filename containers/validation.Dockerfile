FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
WORKDIR /workspace
COPY . /workspace
RUN python -m pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home validator && mkdir results && chown -R validator:validator /workspace
USER validator
ENV SHIFTSTEAD_EXECUTION="Colima Linux VM container; correctness only, not native performance"
CMD ["python", "-m", "tools.test_suite"]
