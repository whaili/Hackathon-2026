# The remote validation host already carries this image locally. Keeping the
# base configurable also allows deployment on a normal Python image elsewhere.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

WORKDIR /app
COPY src/game_backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/game_backend ./game_backend

EXPOSE 8080
ENTRYPOINT []
CMD ["uvicorn", "game_backend.server:app", "--host", "0.0.0.0", "--port", "8080"]
