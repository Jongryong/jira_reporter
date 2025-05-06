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


# --- 신규: 지연된 이슈 찾기 도구 ---
@mcp.tool()
async def find_delayed_issues(
    ctx: Context,
    project_key: Annotated[
        Optional[str],
        Field(description="검색 범위를 제한할 특정 Jira 프로젝트 키 (예: 'PROJ')."),
    ] = None,
    max_results: Annotated[
        int, Field(description="보고서에 포함할 최대 지연 이슈 개수.")
    ] = 15,
    explain_delay: Annotated[
        bool,
        Field(
            description="True로 설정하면, 클라이언트 LLM을 사용하여 각 이슈의 지연 이유를 코멘트를 기반으로 추론합니다."
        ),
    ] = False,
) -> str:
    """
    마감일이 지났지만 아직 해결되지 않은 Jira 이슈를 찾아 보고합니다.
    선택적으로 클라이언트 LLM을 사용하여 각 이슈의 지연 이유를 분석합니다.
    """
    await ctx.info("지연된 Jira 이슈 검색 중...")

    # 1. JQL 쿼리 구성
    jql_parts = ["duedate < now()", "resolution = Unresolved"]
    if project_key:
        jql_parts.insert(0, f"project = '{project_key.upper()}'")

    final_jql = " AND ".join(jql_parts) + " ORDER BY duedate ASC" # 가장 오래된 마감일 순서
    await ctx.debug(f"지연 이슈 검색 JQL: {final_jql}")

    issues = []
    comments_dict = {}
    try:
        # Jira 클라이언트 연결 (별도 스레드에서 실행)
        jira_client = await asyncio.to_thread(get_jira_client)
        await ctx.info("Jira 연결 성공.")

        # 지연된 이슈 검색 (동기 호출을 별도 스레드에서 실행)
        # 코멘트도 함께 가져오기 위해 'comment' 필드 요청 및 expand 사용
        search_fields = "summary,status,assignee,duedate,comment"
        issues = await asyncio.to_thread(
            jira_client.search_issues,
            final_jql,
            maxResults=max_results,
            fields=search_fields,
            # expand='comment' # 주석 처리: search_issues의 expand는 제한적일 수 있음
        )
        await ctx.info(f"JQL 쿼리 결과: {len(issues)}개의 지연된 이슈 발견 (최대 {max_results}개).")

        # 지연 이유 설명을 요청했고 이슈가 있다면, 각 이슈의 코멘트 가져오기 (별도 스레드)
        if explain_delay and issues:
            await ctx.info("지연 이유 분석을 위해 코멘트 가져오는 중...")
            async def fetch_comments(issue_key):
                try:
                    # 각 코멘트 가져오기도 동기 호출이므로 스레드 사용
                    comments = await asyncio.to_thread(jira_client.comments, issue_key)
                    # 최신 코멘트 3개만 사용 (예시)
                    return comments[-5:]
                except Exception as e:
                    await ctx.warning(f"[{issue_key}] 코멘트 로딩 중 오류: {e}")
                    return []

            # 여러 이슈의 코멘트를 병렬로 가져오기 시도
            comment_tasks = {issue.key: asyncio.create_task(fetch_comments(issue.key)) for issue in issues}
            await asyncio.gather(*comment_tasks.values())

            for key, task in comment_tasks.items():
                 comments_dict[key] = task.result()

            await ctx.info("코멘트 로딩 완료.")

    except (ConnectionError, JIRAError, ValueError) as e:
        await ctx.error(f"Jira 상호작용 실패: {e}")
        return f"오류: Jira 보고서를 생성할 수 없습니다. {e}"
    except Exception as e:
        await ctx.error(f"예상치 못한 오류 발생: {e}", logger_name="jira_tool")
        return f"오류: 보고서 생성 중 예상치 못한 오류 발생: {e}"

    # --- 보고서 형식화 ---
    if not issues:
        return "검색 조건에 맞는 지연된 이슈가 없습니다."

    report_lines = [f"Jira 지연 이슈 보고서 ({datetime.now().strftime('%Y-%m-%d')})"]
    report_lines.append(f"사용된 JQL: {final_jql}")
    report_lines.append(f"발견된 이슈 {len(issues)}개 (최대 {max_results}개 표시):")
    report_lines.append("-" * 30)

    llm_explanations = {}
    # --- (선택적) LLM 지연 이유 분석 ---
    if explain_delay:
        await ctx.info("클라이언트 LLM에게 지연 이유 분석 요청 중...")
        llm_tasks = {}
        for issue in issues:
            latest_comments = comments_dict.get(issue.key, [])
            if not latest_comments:
                llm_explanations[issue.key] = "최근 코멘트 없음."
                continue

            # 코멘트 텍스트 준비 (최신 3개)
            comment_texts = "\n---\n".join(
                [f"작성자: {c.author.displayName}, 날짜: {c.created.split('T')[0]}\n{c.body}" for c in latest_comments]
            )
            # LLM 프롬프트 생성
            prompt = textwrap.dedent(f"""
                다음 Jira 이슈는 마감일({issue.fields.duedate})이 지났지만 아직 '{issue.fields.status.name}' 상태입니다.
                이슈 키: {issue.key}
                제목: {issue.fields.summary}
                최근 코멘트 내용을 바탕으로 지연되는 주된 이유를 간략하게 추론해주세요. (예: "정보 기다리는 중", "다른 작업에 막힘", "담당자 부재", "이슈 복잡도 증가", "코멘트 없음" 등)

                최근 코멘트:
                {comment_texts}

                지연 이유 추론:
            """).strip()

            # 각 이슈에 대해 비동기적으로 LLM 호출 작업 생성
            llm_tasks[issue.key] = asyncio.create_task(ctx.sample(prompt, max_tokens=100))

        # 모든 LLM 작업이 완료될 때까지 기다림
        await asyncio.gather(*llm_tasks.values())

        # 결과 취합
        for key, task in llm_tasks.items():
            try:
                response = task.result()
                llm_explanations[key] = response.text.strip()
            except Exception as e:
                await ctx.warning(f"[{key}] LLM 요약 실패: {e}")
                llm_explanations[key] = "LLM 분석 실패"

        await ctx.info("LLM 지연 이유 분석 완료.")

    # --- 최종 보고서 생성 ---
    for issue in issues:
        key = issue.key
        summary = issue.fields.summary
        status = issue.fields.status.name
        assignee = (
            issue.fields.assignee.displayName if issue.fields.assignee else "미할당"
        )
        due_date = issue.fields.duedate if issue.fields.duedate else "마감일 없음"
        report_lines.append(
            f"\n- [{key}] {summary}\n  상태: {status}, 담당자: {assignee}, 마감일: {due_date}"
        )
        if explain_delay:
            reason = llm_explanations.get(key, "분석 정보 없음.")
            report_lines.append(f"  추정 지연 이유: {reason}")

    return "\n".join(report_lines)

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