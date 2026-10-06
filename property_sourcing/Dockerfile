FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

ENV DASHBOARD_PORT=8000
EXPOSE 8000

# Default command runs the dashboard; override with `scheduler.py` to run
# the automation loop instead (see docker-compose.yml, which runs both).
CMD ["python", "app.py"]
