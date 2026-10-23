"""Production adapters.

Each adapter is import-safe: external SDKs are imported lazily inside the adapter so the
composition root and business modules never depend on them. The port implementations
land with their owning tickets (see each module's docstring).
"""
