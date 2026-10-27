"""Gunicorn settings for WeddingSnap.  Start with:  gunicorn -c gunicorn.conf.py weddingsnap.wsgi

Values can be overridden with environment variables (e.g. in the systemd service).
"""
import os

# Only nginx talks to gunicorn, over localhost. nginx handles HTTPS and the public ports.
bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")

# ONE worker process: photo indexing runs on background threads inside it, and its caches (face models,
# search data) are shared. More processes would duplicate ~200 MB each and could index the same photos twice.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))  # requests handled at the same time

# Large uploads and guests' "Download all" zips can take a while.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = 5

# Trust X-Forwarded-* headers only from nginx on this machine.
forwarded_allow_ips = "127.0.0.1"

# Logs go to journald via systemd:  journalctl -u weddingsnap -f
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")

# Heartbeat files in RAM instead of on disk.
if os.path.isdir("/dev/shm"):
    worker_tmp_dir = "/dev/shm"

proc_name = "weddingsnap"
