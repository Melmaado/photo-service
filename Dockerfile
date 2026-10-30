FROM python:3.12.6-slim
WORKDIR /app
COPY requirements/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
CMD ["gunicorn", "app:app","--threads=1","--workers=1", "--bind",  "0.0.0.0:8080"]