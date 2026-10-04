"""
Public deep-health endpoint (DEP-4).

Exposes GET /api/v1/health — "the system works" — for the deploy script
and external monitors, distinct from the Docker-internal GET /health
liveness probe in main.py, which only answers "the process is alive".
"""
