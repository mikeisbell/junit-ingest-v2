SELECT 'CREATE DATABASE bug_tracker'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'bug_tracker'
)\gexec
