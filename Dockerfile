# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
RUN pip install --no-cache-dir -r requirements.txt

# Make port available to the world outside this container
# Hugging Face Spaces uses 7860 by default
ENV PORT=7860

# Define environment variable
ENV PYTHONUNBUFFERED=1

# Run app.py when the container launches using gunicorn
# Bind to 0.0.0.0 and the PORT environment variable
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 app:app
