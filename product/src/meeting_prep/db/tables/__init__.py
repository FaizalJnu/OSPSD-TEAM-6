"""Table definitions, one module per owning area (for example ``conversations.py``).

Define tables on ``meeting_prep.db.Base``, then add a migration that creates
them (see product/README.md, Database). Each table belongs to the area whose
module defines it; change another area's table only through a migration its
owner reviews.
"""
