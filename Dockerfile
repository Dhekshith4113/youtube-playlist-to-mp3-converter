# Use a lightweight Python version
FROM python:3.9-slim

# Install FFmpeg (Crucial for converting to MP3)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set up the app folder
WORKDIR /app

# Copy files
COPY . .

# Install Python libraries
RUN pip install --no-cache-dir -r requirements.txt

# Run the app using Gunicorn
# FIX DETAILS:
# -k gthread: Uses threads (correct name)
# --threads 4: Allows 4 concurrent threads
# --timeout 600: Allows 10 minutes for a request (crucial for long playlists)
CMD ["gunicorn", "-k", "gthread", "--threads", "4", "--timeout", "600", "-w", "1", "app:app", "-b", "0.0.0.0:10000"]
