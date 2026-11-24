"""The agent: a model interface, a tool registry, and a small loop with limits.

* ``model.py``: ``ModelClient``, with the real ``GroqModel`` and the ``ScriptedModel``
  that tests and CI use instead of a live model.
* ``tools.py``: ``ToolRegistry``. Each tool's arguments are a pydantic model whose JSON
  schema goes to the model, and arguments are validated before the handler runs.
* ``loop.py``: ``run``, which asks the model, runs the tools it calls, and stops on an
  answer or on a limit, a cancellation or a model failure.

The agent reaches providers only through the API service, which checks approval, so
this package never imports the registry, the adapters, the orchestrator or the fakes.
The model, tools and loop also import no web framework; only the agent service's web
entry point, in this package, may (tests/test_import_boundary.py).
"""
