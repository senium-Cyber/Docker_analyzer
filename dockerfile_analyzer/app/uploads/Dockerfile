# Use a general-purpose base image
FROM ubuntu:20.04

# Set the working directory inside the container
WORKDIR /usr/src/app

# Install OpenJDK and other dependencies
RUN apt-get update && apt-get install -y \
    openjdk-11-jdk \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the application's JAR file to the container
COPY target/myapp.jar .

# Copy any additional necessary files, like configuration files
# COPY config/ /usr/src/app/config/

# Expose the port the application runs on
EXPOSE 8080

# Define the command to run the application
CMD ["java", "-jar", "myapp.jar"]
