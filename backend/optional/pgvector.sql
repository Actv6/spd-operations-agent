-- Opt-in only; requires a PostgreSQL server with pgvector installed.
-- M1 does NOT execute this file, generate vectors, or claim vector retrieval.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE chunk_embeddings (
    chunk_id varchar(36) NOT NULL REFERENCES chunks(id),
    provider varchar(100) NOT NULL,
    model varchar(100) NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions = 1024),
    source_hash varchar(64) NOT NULL,
    embedding vector(1024) NOT NULL,
    PRIMARY KEY (chunk_id, provider, model)
);
