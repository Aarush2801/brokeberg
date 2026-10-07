"""Extraction DAG: raw_item -> span-grounded, canonical-ID-linked records (passes 0-5).

Each pass is a separate function with a strict pydantic output; `run.py` chains and persists them.
"""
