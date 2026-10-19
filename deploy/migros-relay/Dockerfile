# Ретранслятор Migros Yemek для домашнего сервера (D434, docs/17-aggregators.md).
# Один файл на стандартной библиотеке — зависимостей нет.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
RUN useradd --system --no-create-home relay
COPY src/ratings/aggregators/migros_relay.py /app/migros_relay.py
USER relay
EXPOSE 9021
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:9021/health',timeout=4)"
CMD ["python", "/app/migros_relay.py"]
