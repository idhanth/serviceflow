-- Runs once, on the first start of an empty data volume, as the image's superuser.
--
-- The application connects as `serviceflow`, which is deliberately NOT a
-- superuser and cannot bypass row level security: superusers ignore every RLS
-- policy, so connecting as one would silently switch tenant isolation off.
-- Development credentials only; never reuse them outside this compose file.
CREATE ROLE serviceflow LOGIN PASSWORD 'serviceflow' NOSUPERUSER CREATEDB NOBYPASSRLS;
CREATE DATABASE serviceflow OWNER serviceflow;
