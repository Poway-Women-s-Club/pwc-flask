FROM docker.io/python:3.11

  WORKDIR /

  # --- [Install python and pip] ---
  RUN apt-get update && apt-get upgrade -y && \
      apt-get install -y python3 python3-pip git
  COPY . /

  RUN pip install --no-cache-dir -r requirements.txt
  RUN pip install gunicorn

  ENV GUNICORN_CMD_ARGS="--workers=1 --bind=0.0.0.0:8327"

  EXPOSE 8327

  # Define environment variable
  ENV FLASK_ENV=production

  CMD [ "gunicorn", "main:app" ]