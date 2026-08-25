"""HTTP interface for the React frontend.

Thin FastAPI layer over the service functions that read the mart/raw
layers of the DuckDB warehouse. Read-only alongside the Dagster writer,
except rating requests, which enqueue pipeline work.
"""
