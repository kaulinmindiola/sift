"""Pure domain rules for imports.

Nothing in this package may import Django, DRF, Celery, Channels, boto3,
psycopg or redis (NFR-10). tests/architecture/test_domain_purity.py enforces it.
"""
