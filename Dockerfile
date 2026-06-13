FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD gunicorn -w 2 --preload -b 0.0.0.0:${PORT:-8000} --access-logfile - app:app
