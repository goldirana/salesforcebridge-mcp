# Salesforce Bridge MCP Server

A production-ready [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that connects AI assistants to Salesforce, enabling natural language interactions with your CRM data.

Built with [FastMCP](https://github.com/jlowin/fastmcp) and Python 3.11+.

---

## Features

- **OAuth 2.0 Authentication** — Authorization Code flow with PKCE for secure per-user Salesforce access
- **SOQL Queries** — Execute read-only SOQL queries with built-in safety checks
- **Record CRUD** — Get, create, update, and delete Salesforce records
- **Object Discovery** — Describe sObjects and their fields
- **Case Management** — Dedicated tools for support case workflows
- **Customer Insights** — Consolidated customer/account views
- **Reports** — Access Salesforce report data
- **Role-Based Access** — Admin, CSM, and Viewer roles with tool-level permissions
- **Rate Limiting** — Configurable request throttling per user/role
- **Input Validation** — Schema-based parameter validation for all tools
- **Observability** — Structured logging, metrics, audit trail, and health checks
- **Production Ready** — Docker, Helm, Terraform, and Azure Container Apps support

---

## Quick Start

### Prerequisites

- Python 3.11+
- A Salesforce Connected App with OAuth 2.0 enabled
- Environment variables configured (see below)

### Installation

```bash
# Clone the repository
git clone <repo-url> && cd salesforcebridge-mcp

# Create a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate  # macOS/Linux

# Install in development mode
pip install -e .
```

### Configuration

Create a `.env` file in the project root:

```env
SF_CLIENT_ID=your_connected_app_client_id
SF_CLIENT_SECRET=your_connected_app_client_secret
SF_INSTANCE_URL=https://yourorg.my.salesforce.com
SF_CALLBACK_URL=http://localhost:8000/oauth/callback
SF_API_VERSION=v62.0

HOST=0.0.0.0
PORT=8000
ENV=development
LOG_LEVEL=INFO
DEBUG=false
```

### Running the Server

```bash
python -m src.server
```

The MCP server will start on `http://localhost:8000`.

---

## Authentication Flow

The server uses OAuth 2.0 Authorization Code flow with PKCE:

1. **`auth_start`** — Returns a Salesforce authorization URL for the user to visit
2. User logs in at Salesforce and is redirected to `localhost:8000/oauth/callback`
3. **`auth_complete`** — Pass the full redirect URL to exchange the code for tokens
4. **`auth_status`** — Check if a session is active
5. **`auth_revoke`** — Revoke tokens and log out

---

## Available Tools

| Tool | Description | Roles |
|------|-------------|-------|
| `soql_query` | Execute read-only SOQL queries | admin, csm, viewer |
| `get_record` | Retrieve a record by ID | admin, csm, viewer |
| `create_record` | Create a new record | admin, csm |
| `update_record` | Update an existing record | admin, csm |
| `delete_record` | Delete a record | admin |
| `describe_object` | Describe sObject fields and metadata | admin, csm, viewer |
| `get_case` | Get case details | admin, csm, viewer |
| `create_case` | Create a support case | admin, csm |
| `get_customer` | Get consolidated customer view | admin, csm, viewer |
| `run_report` | Execute a Salesforce report | admin, csm |

---

## Project Structure

```
src/
├── server.py              # MCP server entrypoint & tool registration
├── config.py              # Environment-based configuration
├── auth/                  # OAuth 2.0 (authorization code + client credentials)
├── authz/                 # Role-based access control
├── integrations/          # Salesforce API client & caching
├── middleware/            # Error handling, validation, rate limiting
├── observability/         # Logging, metrics, audit, health checks
└── tools/                 # MCP tool implementations
    ├── base.py            # BaseTool abstract class & ToolResult
    ├── registry.py        # Auto-discovery tool registry
    ├── query.py           # SOQL queries
    ├── records.py         # Record CRUD
    ├── describe.py        # sObject metadata
    ├── cases.py           # Case management
    ├── customers.py       # Customer insights
    └── reports.py         # Reports
```

---

## Deployment

### Docker

```bash
docker build -t salesforcebridge-mcp .
docker run -p 8000:8000 --env-file .env salesforcebridge-mcp
```

### Docker Compose

```bash
docker-compose up
```

### Kubernetes (Helm)

```bash
helm install salesforce-mcp ./infra/helm -f infra/helm/values.yaml
```

### Azure Container Apps (Terraform)

```bash
cd infra/terraform
terraform init
terraform apply
```

---

## Testing

```bash
# Unit tests
pytest tests/unit/

# Integration tests (requires Salesforce credentials)
pytest tests/integration/

# Load tests
locust -f tests/load/locustfile.py
```

---

## Health Checks

The server exposes MCP resources for health monitoring:

- `health://liveness` — Is the process alive?
- `health://readiness` — Can the server handle requests?

---

## License

Proprietary — All rights reserved.
