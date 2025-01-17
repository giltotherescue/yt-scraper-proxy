# Use an official Python 3 image as a parent image.
FROM python:3.10-slim-buster

# Install system dependencies
RUN apt-get update && apt-get install -y \
    apt-transport-https \
    apt-utils \
    ca-certificates \
    curl \
    gnupg \
    wget \
    unzip \
    # The following are needed for Chromium
    chromium \
    chromium-driver \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Set environment variable to tell Chrome where the driver is
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver
ENV CHROME_PATH=/usr/bin/chromium

# --------------------------------------------------------------------------
# Copy and install Python dependencies
# --------------------------------------------------------------------------
WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code into the container
COPY . /app

# Expose the port Gunicorn will run on
EXPOSE 8080

# Set environment variables for production
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Final command to run your Flask app with Gunicorn
CMD ["gunicorn", "--worker-tmp-dir", "/dev/shm", "app:app", "-b", "0.0.0.0:8080"]
