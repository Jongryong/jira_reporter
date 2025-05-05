# Jira Weekly Reporter MCP Server

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) <!-- Adjust if using a different license -->

This project provides a [FastMCP](https://gofastmcp.com/) server that connects to your Jira instance (Cloud or Server/Data Center) to generate weekly reports based on issue activity. It leverages the `pycontribs-jira` library for Jira interaction and can optionally use the connected client's Large Language Model (LLM) for summarizing the generated report.

## ✨ Features

*   **Jira Connection:** Securely connects to Jira using API tokens stored in a `.env` file.
*   **MCP Tool:** Exposes a `generate_jira_report` tool accessible via the Model Context Protocol.
*   **Flexible Reporting:**
    *   Defaults to reporting issues updated in the last 7 days.
    *   Allows specifying a custom JQL query.
    *   Can filter reports by a specific Jira project key.
    *   Limits the number of results returned (configurable).
*   **(Optional) LLM Summarization:** Can use the *client's* LLM (via `ctx.sample()`) to provide a concise summary of the report.
*   **Asynchronous Handling:** Properly handles synchronous Jira library calls within the asynchronous FastMCP server using `asyncio.to_thread`.

## 📋 Prerequisites

*   Python 3.10 or later.
*   [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or `pip` for package management.
*   Access to a Jira instance (Cloud, Server, or Data Center).
*   A Jira API Token (Personal Access Token for Server/DC).

## ⚙️ Setup

1.  **Clone the Repository (if applicable):**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-directory>
    ```

2.  **Install Dependencies:**
    We recommend using `uv`:
    ```bash
    uv pip install fastmcp "jira[cli]" python-dotenv httpx anyio
    ```
    Alternatively, use `pip`:
    ```bash
    pip install fastmcp "jira[cli]" python-dotenv httpx anyio
    ```

3.  **Create `.env` File:**
    Create a file named `.env` in the same directory as `jira_reporter_server.py`. Add your Jira connection details:
    ```dotenv
    # .env
    JIRA_URL=https://your-domain.atlassian.net  # Your Jira Cloud URL or Self-Hosted URL
    JIRA_USERNAME=your_email@example.com       # Your Jira login email
    JIRA_API_TOKEN=your_api_token_or_pat       # Your generated API Token or PAT
    ```
    *   **Security:**
        *   **Never commit your `.env` file to version control!** Add `.env` to your `.gitignore` file.
        *   **Jira Cloud:** Generate an API token from your Atlassian account settings: [Manage API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/).
        *   **Jira Server/Data Center:** Generate a Personal Access Token (PAT) from your Jira user profile settings: [Using Personal Access Tokens](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html).

## ▶️ Running the Server

You can run the server in several ways:

1.  **Directly with Python (for stdio clients like Claude Desktop):**
    This is the standard way for clients that expect to execute a script.
    ```bash
    python jira_reporter_server.py
    ```

2.  **Using the FastMCP CLI:**
    This is useful for testing or running with different transports.
    ```bash
    # Run with default stdio transport
    fastmcp run jira_reporter_server.py

    # Run with SSE transport on port 8001
    fastmcp run jira_reporter_server.py --transport sse --port 8001
    ```

## 🛠️ Usage (MCP Tool)

The server exposes one primary tool to MCP clients:

*   **Tool Name:** `generate_jira_report`
*   **Description:** Generates a report of Jira issues based on a JQL query (defaulting to recently updated). Optionally summarizes the report using the client's LLM.

**Parameters:**

| Parameter     | Type         | Required | Default                  | Description                                                                                                    |
| :------------ | :----------- | :------- | :----------------------- | :------------------------------------------------------------------------------------------------------------- |
| `jql_query`   | `string`     | No       | `updated >= -7d ORDER BY updated DESC` | Optional JQL query. If omitted, the default is used.                                                  |
| `project_key` | `string`     | No       | `None`                   | Optional Jira project key (e.g., "PROJ") to limit the search scope (added as `project = 'KEY' AND ...`). |
| `max_results` | `integer`    | No       | `50`                     | Maximum number of issues to include in the raw report data.                                                    |
| `summarize`   | `boolean`    | No       | `false`                  | If `true`, the server will request a summary from the *client's* LLM via `ctx.sample()`.                       |

**Example Client Call (Conceptual):**

An MCP client would interact with this tool like this:

```json
// Request to the MCP server
{
  "method": "tools/call",
  "params": {
    "name": "generate_jira_report",
    "arguments": {
      "project_key": "MYPROJ",
      "summarize": true,
      "max_results": 20
    }
  }
}

// Potential Response from the MCP server (if summarize=true)
{
  "isError": false,
  "content": [
    {
      "type": "text",
      "text": "**Summary:**\n[LLM generated summary based on the report below]...\n\n**Full Report:**\nJira Report (YYYY-MM-DD)\nQuery: project = 'MYPROJ' AND updated >= -7d ORDER BY updated DESC\nFound X issues (showing max 20):\n--------------------\n- [MYPROJ-123] Fix login bug | Status: Done | Assignee: Jane Doe | Updated: YYYY-MM-DD HH:MM\n- [MYPROJ-124] Add new feature | Status: In Progress | Assignee: John Smith | Updated: YYYY-MM-DD HH:MM\n..."
    }
  ]
}
```

## 📦 Server Dependencies
The FastMCP constructor includes dependencies=["jira"]. This tells tools like fastmcp install that the jira library is required for this server to function correctly when creating isolated environments.

## 🤝 Contributing
Contributions are welcome! Please feel free to submit issues or pull requests.

## 📄 License
MIT License