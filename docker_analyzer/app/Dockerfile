FROM ubuntu:20.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get install -y build-essential curl wget git libjpeg-dev libpng-dev && rm -rf /var/lib/apt/lists/*
RUN apt-get install -y python3 python3-pip
RUN pip3 install torch torchvision torchaudio flask
WORKDIR /app
COPY . /app
ENV FLASK_APP=web_app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5000
EXPOSE 5000
CMD ["flask", "run"]