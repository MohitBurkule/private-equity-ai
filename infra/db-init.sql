-- Runs once on first Postgres start (docker-entrypoint-initdb.d).
-- pe_owner owns the schema and runs migrations; pe_app serves requests and is bound by RLS.
CREATE ROLE pe_owner LOGIN PASSWORD 'change-me-owner';
CREATE ROLE pe_app LOGIN PASSWORD 'change-me-app' NOSUPERUSER NOBYPASSRLS;
ALTER DATABASE pe OWNER TO pe_owner;
GRANT ALL ON SCHEMA public TO pe_owner;
GRANT USAGE ON SCHEMA public TO pe_app;
CREATE EXTENSION IF NOT EXISTS vector;
