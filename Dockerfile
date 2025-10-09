FROM python:3.13-slim-bookworm

# Set working directory
WORKDIR /app

# Install system dependencies and upgrade packages to fix vulnerabilities
RUN apt-get update && apt-get dist-upgrade -y && apt-get install -y \
    gcc \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application
COPY . .

# Create volume for persistent data
VOLUME ["/app/data"]

# Set environment for database path
ENV DB_PATH=/app/data/pal_bot.sqlite

# Run the bot
CMD ["python", "bot.py"]
