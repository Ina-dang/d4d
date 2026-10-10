FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SKYTRACE_DATA_DIR=/data
WORKDIR /srv/gyeopnun
COPY pyproject.toml ./
COPY app ./app
COPY analysis ./analysis
COPY frame ./frame
COPY docs ./docs
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home gyeopnun \
    && mkdir /data && chown gyeopnun:gyeopnun /data
USER gyeopnun
EXPOSE 8766
# Linux host networking keeps Ollama on loopback. Put an HTTPS reverse proxy in front.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8766", "--workers", "1", "--no-proxy-headers"]
