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
*   [FastMCP CLI](https://gofastmcp.com/getting-started/installation) installed and available in your system's PATH.

## ⚙️ Setup

1.  **Clone the Repository (if applicable):**
    ```bash
    git clone https://github.com/Jongryong/jira_reporter.git
    cd jira_reporter
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
    Create a file named `.env` in the *same directory* as `jira_reporter_server.py`. Add your Jira connection details:
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

## ▶️ Running the Server (Standalone)

You can run the server independently for testing or other purposes:

1.  **Directly with Python:**
    ```bash
    python jira_reporter_server.py
    ```

2.  **Using the FastMCP CLI:**
    ```bash
    fastmcp run jira_reporter_server.py
    ```
    To run with SSE (e.g., for remote access):
    ```bash
    fastmcp run jira_reporter_server.py --transport sse --port 8001
    ```

## 🖥️ Using with Claude Desktop

To make this server available as a tool within the Claude Desktop application:

1.  **Ensure Prerequisites:** Make sure `fastmcp` is installed and accessible in your system's PATH, as the configuration below uses the `fastmcp` command.

2.  **Locate Claude Config File:** Find the `claude_desktop_config.json` file. Its location depends on your operating system:
    *   **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
    *   **Windows:** `%APPDATA%\Claude\claude_desktop_config.json` (usually `C:\Users\<YourUsername>\AppData\Roaming\Claude\claude_desktop_config.json`)
    *   **Linux:** `~/.config/Claude/claude_desktop_config.json` (or `$XDG_CONFIG_HOME/Claude/`)

3.  **Edit the Config File:** Open `claude_desktop_config.json` in a text editor.

4.  **Add Server Configuration:** Find the `"mcpServers"` object within the JSON (if it doesn't exist, create it as an empty object `{}`). Add the following entry inside `mcpServers`, making sure to replace `"path/to/your/jira_reporter_server.py"` with the **absolute path** to your script:

    ```json
    {
      "mcpServers": {
        // ... other servers might be here ...

        "jira_report": {
          "command": "fastmcp",
          "args": [
            "run",
            "/path/to/your/jira_reporter_server.py" // <-- IMPORTANT: Use the full, absolute path here
          ]
        }

        // ... other servers might be here ...
      }
      // ... rest of your Claude config ...
    }
    ```
    *   `"jira_report"`: This is the internal name Claude uses. You can change it if desired.
    *   `"command": "fastmcp"`: Tells Claude to use the `fastmcp` command-line tool.
    *   `"args": [...]`: Tells Claude to run `fastmcp run /path/to/your/jira_reporter_server.py`.

5.  **Save and Restart:** Save the `claude_desktop_config.json` file and restart the Claude Desktop application.

6.  **Invoke the Tool:** You should now be able to use the tool in Claude by mentioning the server name defined in the Python script (`Jira Weekly Reporter`). For example:
    `@Jira Weekly Reporter generate jira report for project MYPROJ and summarize it`

## 🛠️ MCP Tool Details

*   **Tool Name:** `generate_jira_report`
*   **Description:** Generates a report of Jira issues based on a JQL query (defaulting to recently updated). Optionally summarizes the report using the client's LLM.

**Parameters:**

| Parameter     | Type         | Required | Default                  | Description                                                                                                    |
| :------------ | :----------- | :------- | :----------------------- | :------------------------------------------------------------------------------------------------------------- |
| `jql_query`   | `string`     | No       | `updated >= -7d ORDER BY updated DESC` | Optional JQL query. If omitted, the default is used.                                                  |
| `project_key` | `string`     | No       | `None`                   | Optional Jira project key (e.g., "PROJ") to limit the search scope (added as `project = 'KEY' AND ...`). |
| `max_results` | `integer`    | No       | `50`                     | Maximum number of issues to include in the raw report data.                                                    |
| `summarize`   | `boolean`    | No       | `false`                  | If `true`, the server will request a summary from the *client's* LLM via `ctx.sample()`.                       |

## 📦 Server Dependencies

The `FastMCP` constructor includes `dependencies=["jira"]`. This tells tools like `fastmcp install` that the `jira` library is required for this server to function correctly when creating isolated environments.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📄 License

MIT License