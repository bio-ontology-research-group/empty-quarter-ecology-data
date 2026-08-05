# Master Control Tool (`eq_control.py`)

The **Empty Quarter Master Control Tool** (`eq_control.py`) is a unified command-line interface (CLI) designed to streamline the development, deployment, and maintenance of the Empty Quarter platform. It consolidates build processes, validation suites, data synchronization, and infrastructure management into a single, scriptable entry point.

## 🚀 Setup & Execution with `uv`

This project uses [`uv`](https://github.com/astral-sh/uv) for Python dependency management and execution.

### Prerequisites
Ensure `uv` is installed and the project environment is set up:
```bash
# Install dependencies
uv pip install -r requirements.txt
```

### Running the Tool
You can run the tool directly via `uv`:

```bash
uv run python eq_control.py [COMMAND] [OPTIONS]
```

Or, if the script is executable (`chmod +x eq_control.py`):

```bash
uv run ./eq_control.py [COMMAND] [OPTIONS]
```

*Note: All examples below assume `uv run ./eq_control.py` or simply `./eq_control.py` if running in an activated environment.*

---

## 🌍 Global Options

These options apply to all commands:

*   `--remote [HOST]`
    *   **Description:** Executes the command on a remote server via SSH.
    *   **Default:** `None` (Runs locally).
    *   **Usage:** `--remote ws` (Connects to `root@ws`).
    *   **Note:** Requires SSH key authentication to be configured for the target host.

---

## 🛠️ Command Reference

### 1. `build`
Regenerates the Knowledge Graph (RDF/Turtle) from source data.

*   **Syntax:** `build [--scope SCOPE] [--clean] [--reload | --no-reload]`
*   **Options:**
    *   `--scope`: Comma-separated list of data scopes to rebuild.
        *   **Values:** `all` (default), `ontology`, `samples`, `measurements`, `xrf`, `dna`, `sra`, `taxonomy`, `qc`.
    *   `--clean`: Wipes the Virtuoso database and stops containers before building. Equivalent to a "Full Reset".
    *   `--reload`: Reloads the generated data into Virtuoso immediately after building (Default: `True`). Use `--no-reload` to skip.
*   **Examples:**
    ```bash
    # Incremental update of Taxonomy and Samples
    uv run ./eq_control.py build --scope taxonomy,samples

    # Full hard reset on the remote server
    uv run ./eq_control.py build --clean --remote ws
    ```

### 2. `validate`
Runs consistency checks and SHACL/ShEx validation suites.

*   **Syntax:** `validate [--scope SCOPE]`
*   **Options:**
    *   `--scope`: Comma-separated list of validation suites.
        *   **Values:** `all` (default), `original`, `materialized`, `taxonomy`.
*   **Examples:**
    ```bash
    # Run all validations locally
    uv run ./eq_control.py validate

    # Check taxonomy completeness on remote
    uv run ./eq_control.py validate --scope taxonomy --remote ws
    ```

### 3. `sync`
Synchronizes code or data between environments.

*   **Syntax:** `sync --target [code|data] [--host HOST] [--source SOURCE]`
*   **Options:**
    *   `--target`:
        *   `code`: Pushes local source code to a remote host (e.g., `ws`). Excludes `.git`, `virtuoso_db`, and processed data.
        *   `data`: Pulls processed data from a source (e.g., `dragon`) to the current environment.
    *   `--host`: Destination host for `code` sync (Default: `ws`).
    *   `--source`: Source host for `data` sync (Default: `dragon`).
*   **Examples:**
    ```bash
    # Deploy code to 'ws'
    uv run ./eq_control.py sync --target code

    # Pull latest processed data from 'dragon' cluster
    uv run ./eq_control.py sync --target data
    ```

### 4. `infra`
Manages the Docker-based infrastructure (Virtuoso & Website).

*   **Syntax:** `infra [start|stop|logs]`
*   **Commands:**
    *   `start`: Builds and starts containers (`docker-compose up -d --build`).
    *   `stop`: Stops and removes containers (`docker-compose down`).
    *   `logs`: Tails container logs (`docker-compose logs -f`).
*   **Examples:**
    ```bash
    # Restart remote infrastructure
    uv run ./eq_control.py infra stop --remote ws
    uv run ./eq_control.py infra start --remote ws

    # Watch logs locally
    uv run ./eq_control.py infra logs
    ```

### 5. `inspect`
Quickly views key configuration and definition files.

*   **Syntax:** `inspect [ontology|shex|schema]`
*   **Targets:**
    *   `ontology`: Displays the head of `final_ecosystem.owl`.
    *   `shex`: Lists SRA ShEx schemas.
    *   `schema`: Lists configuration schemas.
*   **Examples:**
    ```bash
    uv run ./eq_control.py inspect ontology
    ```

### 6. `process`
Runs auxiliary processing tasks.

*   **Syntax:** `process [photos|taxonomy]`
*   **Tasks:**
    *   `photos`: Runs `process_photos.py` to organize gallery images.
    *   `taxonomy`: Runs `generate_taxonomy_abox.groovy` (shortcut).
*   **Examples:**
    ```bash
    uv run ./eq_control.py process photos
    ```
