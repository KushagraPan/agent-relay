# 1. Base Python image matching project requirement (>=3.11)
FROM python:3.11-slim-bookworm

# 2. Install uv binary directly from official Astral multi-arch image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 3. Set the application working directory inside container
WORKDIR /app

# 4. Configure uv behavior for containerized build
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# 5. Copy dependency definitions first to take advantage of Docker layer caching
COPY pyproject.toml uv.lock ./

# 6. Install dependencies defined in uv.lock into a container virtual environment (.venv)
RUN uv sync --frozen --no-install-project

# 7. Copy remaining application source code into container
COPY . .

# 8. Add the project virtual environment to PATH so uvicorn and dependencies are directly executable
ENV PATH="/app/.venv/bin:$PATH"

# 9. Document container port
EXPOSE 8000

# 10. Start Uvicorn bound to 0.0.0.0 (listen on all network interfaces)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
