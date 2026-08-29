"""Business logic.

Route handlers stay thin: they resolve the caller, call into here, and shape the
response. Every function in this package takes the tenant scope explicitly and
filters on it - no query reaches the database without an organization filter
(PRD 4, 5, 61).
"""
