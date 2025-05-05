import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Annotated, List, Optional

import httpx
from dotenv import load_dotenv
from jira import JIRA
from jira.exceptions import JIRAError
from pydantic import Field

from fastmcp import Context, FastMCP

# --- Configuration ---
# Load credentials from .env file
load_dotenv()

JIRA_URL = os.environ.get("JIRA_URL")
JIRA_USERNAME = os.environ.get("JIRA_USERNAME")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN")

# --- MCP Server Setup ---
mcp = FastMCP(
    name="Jira Weekly Reporter",
    instructions="Provides tools to generate weekly reports from Jira.",
    # Add jira library as a dependency hint for installation tools
    dependencies=["jira"],
)

# Helper function to connect to Jira (synchronous)
def get_jira_client() -> JIRA:
    """Connects to Jira using environment variables."""
    if not all([JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN]):
        raise ValueError(
            "JIRA_URL, JIRA_USERNAME, and JIRA_API_TOKEN must be set in environment or .env file."
        )
    try:
        # Using API token for basic_auth as recommended for Jira Cloud/Server PATs
        # Note: The underlying 'jira' library call is synchronous
        jira_client = JIRA(
            server=JIRA_URL, basic_auth=(JIRA_USERNAME, JIRA_API_TOKEN), max_retries=1
        )
        # Test connection
        jira_client.myself()
        return jira_client
    except JIRAError as e:
        raise ConnectionError(f"Failed to connect to Jira: {e.text}") from e
    except Exception as e:
        raise ConnectionError(f"An unexpected error occurred during Jira connection: {e}") from e

# --- MCP Tool Definition ---
@mcp.tool()
async def generate_jira_report(
    ctx: Context,
    jql_query: Annotated[
        Optional[str],
        Field(
            description="Optional JQL query. If not provided, defaults to finding issues updated in the last 7 days."
        ),
    ] = None,
    project_key: Annotated[
        Optional[str],
        Field(description="Optional project key to limit the search."),
    ] = None,
    max_results: Annotated[
        int, Field(description="Maximum number of issues to include in the raw report.")
    ] = 50,
    summarize: Annotated[
        bool, Field(description="If true, ask the client's LLM to summarize the report.")
    ] = False,
) -> str:
    """
    Generates a report of Jira issues based on a JQL query (defaulting to recently updated).
    Optionally summarizes the report using the client's LLM.
    """
    await ctx.info("Generating Jira report...")

    if jql_query:
        final_jql = jql_query
        await ctx.debug(f"Using provided JQL: {final_jql}")
    else:
        # Default JQL: updated in the last 7 days, ordered by update time
        final_jql = "updated >= -7d ORDER BY updated DESC"
        if project_key:
            final_jql = f"project = '{project_key.upper()}' AND {final_jql}"
            await ctx.debug(f"Using default JQL for project {project_key}: {final_jql}")
        else:
            await ctx.debug(f"Using default JQL: {final_jql}")

    try:
        # Run the synchronous Jira library calls in a separate thread
        # This prevents blocking the main async event loop
        jira_client = await asyncio.to_thread(get_jira_client)
        await ctx.info("Connected to Jira successfully.")

        # Fetch issues (synchronous call wrapped in thread)
        issues = await asyncio.to_thread(
            jira_client.search_issues, final_jql, maxResults=max_results
        )
        await ctx.info(f"Found {len(issues)} issues matching JQL.")

    except (ConnectionError, JIRAError, ValueError) as e:
        await ctx.error(f"Jira interaction failed: {e}")
        return f"Error: Could not generate Jira report. {e}"
    except Exception as e:
        await ctx.error(f"An unexpected error occurred: {e}", logger_name="jira_tool")
        return f"Error: An unexpected error occurred while generating the report: {e}"

    # --- Format the Report ---
    if not issues:
        return "No issues found matching the criteria for the weekly report."

    report_lines = [f"Jira Report ({datetime.now().strftime('%Y-%m-%d')})"]
    report_lines.append(f"Query: {final_jql}")
    report_lines.append(f"Found {len(issues)} issues (showing max {max_results}):")
    report_lines.append("-" * 20)

    for issue in issues:
        key = issue.key
        summary = issue.fields.summary
        status = issue.fields.status.name
        assignee = (
            issue.fields.assignee.displayName if issue.fields.assignee else "Unassigned"
        )
        updated = datetime.strptime(
            issue.fields.updated.split(".")[0], "%Y-%m-%dT%H:%M:%S"
        ).strftime("%Y-%m-%d %H:%M")
        report_lines.append(
            f"- [{key}] {summary} | Status: {status} | Assignee: {assignee} | Updated: {updated}"
        )

    raw_report = "\n".join(report_lines)

    # --- Optional Summarization ---
    if summarize:
        await ctx.info("Requesting summary from client LLM...")
        summary_prompt = f"Please summarize the following Jira report, highlighting key updates or trends:\n\n{raw_report}"
        try:
            summary_response = await ctx.sample(summary_prompt, max_tokens=300)
            summary_text = summary_response.text
            await ctx.info("Summary received from client LLM.")
            # Prepend summary to the raw report
            return f"**Summary:**\n{summary_text}\n\n**Full Report:**\n{raw_report}"
        except Exception as e:
            await ctx.warning(f"Failed to get summary from client LLM: {e}. Returning raw report.")
            return raw_report # Fallback to raw report if summarization fails
    else:
        return raw_report # Return raw report if summarization not requested

# --- Standard Execution Block ---
if __name__ == "__main__":
    print(f"Starting '{mcp.name}' MCP server...")
    # Ensure required environment variables are set before running
    if not all([JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN]):
        print(
            "Error: JIRA_URL, JIRA_USERNAME, and JIRA_API_TOKEN must be set in environment or .env file.",
            file=sys.stderr,
        )
        sys.exit(1)
    mcp.run() # Runs with default stdio transport