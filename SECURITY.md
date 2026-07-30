# Security

## Supported version

Security fixes are applied to the latest commit on `main`.

## Reporting a vulnerability

Please report vulnerabilities through a
[private GitHub security advisory](https://github.com/RayyanHai/journal-rag/security/advisories/new)
instead of opening a public issue.

## Deployment boundary

Journal RAG is a local, single-user application:

- FastAPI binds to `127.0.0.1`.
- Browser requests are limited to the built app and the local Vite development server.
- ChromaDB runs through the embedded `PersistentClient`; its network server is never started.
- The API has no authentication and must not be bound to a public interface as-is.

ChromaDB 1.5.9 is currently flagged by `PYSEC-2026-311`, which affects Chroma's
unauthenticated network server collection endpoint. That endpoint is not exposed by
this project. Upgrade ChromaDB once a compatible fixed release is available.
