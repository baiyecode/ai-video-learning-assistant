"""Business modules (catalog, identity, media, analysis, ops).

Each module owns ``models.py`` (SQLAlchemy tables) and ``router.py`` (HTTP routes), and
depends only on the ports in ``app.ports``.
"""
