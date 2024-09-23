# Use an official Python runtime as a parent image
FROM python:3.8-slim

RUN echo "BUILDING IMAGE FOR DOCTOR WEB FRAMEWORK"

# Create a non-root user
RUN useradd -ms /bin/bash celeryuser

# Set the working directory in the container
WORKDIR /doctor-web-framework

# Copy the current directory contents into the container at /app
COPY . /doctor-web-framework

# Copy the clear_logs.sh script into the container
# COPY clear_logs.sh /doctor-web-framework/clear_logs.sh

# Make the script executable
RUN chmod +x /doctor-web-framework/clear_logs.sh

# RUN /doctor-web-framework/clear_logs.sh

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r ./requirements.txt

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Adjust number of gunicorn workers for scalable deployment
ENV GUNICORN_WORKERS=3

# CMD ["gunicorn", "-k", "gevent", "-w", "1", "-b", "0.0.0.0:5000", "--log-level", "info", "app:app"]
ENTRYPOINT ["/bin/bash", "-c", "/doctor-web-framework/clear_logs.sh && gunicorn -k gevent -w $GUNICORN_WORKERS -b 0.0.0.0:5000 --log-level info app:app"]