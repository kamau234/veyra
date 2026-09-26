"""Data access patterns.

Repositories own SQL/query detail. They accept an open ``Session`` and never
commit — transaction boundaries live in the service layer.
"""
