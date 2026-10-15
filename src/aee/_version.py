"""Single source of truth for the engine version (Spec 002 FR-4).

``aee.__version__``, the ``aee --version`` CLI output, and the
``metadata.engine_version`` stamp on every assessment all read this
one string, so they cannot drift from each other (FR-4.4). The
``version`` field in ``pyproject.toml`` is kept in lockstep at
release time; see ``docs/versioning.md``.
"""

__version__ = "1.5.2"
