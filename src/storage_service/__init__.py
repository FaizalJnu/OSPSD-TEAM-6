"""Storage service: a small HTTP API for storing and retrieving files.

Suggested reading order for new contributors:

1. ``storage/base.py``: the contract every storage backend follows.
2. ``service.py``: the rules (what is allowed, what fails, and why).
3. ``routers/``: how HTTP requests map onto the service, one module per operation.
4. ``main.py``: where the pieces get plugged together.
"""
