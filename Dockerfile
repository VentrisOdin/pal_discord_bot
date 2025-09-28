FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

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
