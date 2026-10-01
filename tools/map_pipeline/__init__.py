"""Offline map data pipeline for Project Goliath.

Deterministic developer tool: turns ``data/map/source/map.svg`` +
``boundary.yaml`` + ``overrides.yaml`` into ``ids.lock.json`` and (in later
issues) ``manifest.json`` / ``geometry.json``. Never writes to the database
and never modifies its inputs.
"""
