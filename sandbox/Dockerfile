# One throwaway browser per scan. Built once on the sandbox server:
#   docker build -t scansafe-sandbox sandbox/
# Pin this tag to the Playwright version pip installs below if you change either.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble

RUN pip install --no-cache-dir playwright==1.55.0

# Run as the image's unprivileged user, never root.
USER pwuser
WORKDIR /home/pwuser
COPY --chown=pwuser run_scan.py .

ENTRYPOINT ["python", "run_scan.py"]
