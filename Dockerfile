# Uses Microsoft's official Playwright image — comes with all browser dependencies
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

# Persist DB and Facebook session outside the container
VOLUME ["/app/data"]

CMD ["python", "main.py"]
