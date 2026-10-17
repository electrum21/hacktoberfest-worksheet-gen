# Hosted portal only. The generator (Ollama + Streamlit) stays on the tutor's laptop.
#   docker build -t tutor-portal .
#   docker run -p 8000:8000 -v portal-data:/data \
#     -e PORTAL_PUBLIC_URL=https://your-domain.example tutor-portal
FROM python:3.12-slim
WORKDIR /app
COPY requirements-portal.txt .
RUN pip install --no-cache-dir -r requirements-portal.txt
COPY portal ./portal
ENV PORTAL_DB=/data/portal.db PYTHONUNBUFFERED=1
RUN useradd --create-home app && mkdir /data && chown app /data
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')" || exit 1
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--access-logfile", "-", "portal.wsgi:app"]
