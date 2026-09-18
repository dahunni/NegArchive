FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libgl1 + libglib2.0-0: OpenCV headless. cifs-utils: mounting the network share
# NegPy and NegArchive share (M6, app/services/smb.py) — it brings in mount.cifs,
# which is what `mount -t cifs` execs. About 1 MB; the capability to use it is a
# separate decision the Compose file makes.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cifs-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# One directory for everything the archive owns; the compose stack bind-mounts
# the host's ./data over it (roadmap M3). Created here so the image also works
# standalone, without a mount.
ENV DATA_DIR=/data
RUN mkdir -p /data

# Where an SMB share is mounted (M6). Created in the image so the mount point
# exists before anything tries to mount on it; empty until Settings says otherwise.
RUN mkdir -p /mnt/negarchive

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]