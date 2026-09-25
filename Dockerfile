FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
ENV LLMBENCH_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8765
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD []
