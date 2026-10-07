FROM python:3.12-slim
WORKDIR /service
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home worker && mkdir /data && chown worker /data
USER worker
ENV EVIDENCEDESK_DB=/data/evidencedesk.db
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
