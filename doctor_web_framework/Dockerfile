# Use an official Python runtime as a parent image
FROM python:3.8-slim

RUN echo "BUILDING IMAGE FOR DOCTOR WEB FRAMEWORK"

# Create a non-root user
RUN useradd -ms /bin/bash celeryuser

# Set the working directory in the container
WORKDIR /doctor-web-framework

# Copy the current directory contents into the container at /app
COPY . /doctor-web-framework

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

# Set the user to non-root
USER celeryuser

# Run app.py when the container launches
CMD ["python", "run.py"]
