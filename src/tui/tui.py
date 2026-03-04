"""
Agentic Tester — Interactive Terminal UI (Textual)

Fetches test cases from Firebase Firestore, lets users pick a project,
select/deselect individual tests with checkboxes, and execute with live
feedback in split log panels.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from textual import work, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    RichLog,
    Select,
    Static,
)

from src.config import get_settings, Settings
from src.models.test_case import TestCase, TestSuite
from src.storage.firebase_client import FirebaseClient
from src.executor.agent import TestExecutorAgent, InferenceAgent
from src.executor.mcp_config import create_mcp_client

logger = logging.getLogger(__name__)


class RichLogHandler(logging.Handler):
    """Custom logging handler that writes to a Textual RichLog widget."""

    def __init__(self, rich_log: RichLog):
        super().__init__()
        self.rich_log = rich_log
        self.setFormatter(logging.Formatter(
            "[dim]%(asctime)s[/] %(name)s: %(message)s", datefmt="%H:%M:%S"
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname
            if level == "ERROR":
                self.rich_log.write(f"[red]{msg}[/]")
            elif level == "WARNING":
                self.rich_log.write(f"[yellow]{msg}[/]")
            else:
                self.rich_log.write(msg)
        except Exception:
            pass


def _configure_global_logging() -> None:
    root_logger = logging.getLogger()
    log_dir = Path("./outputs")
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(fh)
    root_logger.setLevel(logging.INFO)


def _setup_audit_logger() -> logging.Logger:
    audit = logging.getLogger("tui.audit")
    audit.setLevel(logging.INFO)
    if not audit.handlers:
        log_dir = Path("./outputs")
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "tui_audit.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        audit.addHandler(fh)
    return audit


audit_log = _setup_audit_logger()


# ─── CSS ──────────────────────────────────────────────────────────────

APP_CSS = """
/* ── Config row ── */
#config-row {
    height: 5;
    padding: 1 2;
}

#project-select {
    width: 1fr;
}

.config-label {
    width: 14;
    padding: 1 1 0 0;
    text-style: bold;
}

.config-input {
    width: 1fr;
}

#url-row {
    height: 3;
    padding: 0 2;
}

/* ── Test list ── */
#test-list-header {
    height: 1;
    padding: 0 2;
    text-style: bold;
    color: $accent;
}

#test-list {
    height: 1fr;
    min-height: 6;
    border: solid $accent;
    margin: 0 1;
}

#empty-msg {
    text-align: center;
    padding: 2 0;
    color: $text-muted;
    text-style: italic;
}

/* ── Actions row: compact ── */
#actions-row {
    height: 3;
    padding: 0 2;
}

#selection-info {
    width: 1fr;
    padding: 0 1;
}

.action-btn {
    margin-right: 1;
    min-width: 10;
}

#execute-btn {
    min-width: 18;
}

/* ── Log panels ── */
#log-panels {
    height: 12;
    min-height: 8;
    margin: 0 1;
}

#exec-log-panel {
    width: 1fr;
    height: 100%;
    border: solid $accent;
}

#mcp-log-panel {
    width: 1fr;
    height: 100%;
    border: solid cyan 50%;
}

.panel-title {
    height: 1;
    padding: 0 1;
    text-style: bold;
    background: $accent 15%;
}

#mcp-log-title {
    background: cyan 15%;
}

#exec-log {
    height: 1fr;
}

#mcp-log {
    height: 1fr;
}

/* ── Status bar ── */
#status-bar {
    dock: bottom;
    height: 1;
    padding: 0 2;
    background: $accent 15%;
}

/* ── Test case rows ── */
TestCaseRow {
    height: 2;
    padding: 0 1;
}

TestCaseRow:hover {
    background: $accent 10%;
}

.tc-checkbox {
    width: auto;
    height: 1;
}

.tc-id {
    width: 14;
    color: $accent;
}

.tc-title {
    width: 1fr;
}

.tc-priority-high {
    width: 8;
    color: red;
    text-style: bold;
}

.tc-priority-medium {
    width: 8;
    color: yellow;
}

.tc-priority-low {
    width: 8;
    color: green;
}

.tc-category {
    width: 10;
    color: $text-muted;
}
"""


class TestCaseRow(Horizontal):
    """A single test case row with its own checkbox."""

    def __init__(self, tc_data: dict, **kwargs):
        super().__init__(**kwargs)
        self.tc_data = tc_data
        self.tc_id = tc_data.get("id", "???")

    def compose(self) -> ComposeResult:
        tc = self.tc_data
        priority = tc.get("priority", "medium")
        category = tc.get("category", "")
        title = tc.get("title", "Untitled")

        yield Checkbox("", value=False, id=f"cb-{self.tc_id}", classes="tc-checkbox")
        yield Label(self.tc_id, classes="tc-id")
        yield Label(title, classes="tc-title")
        yield Label(priority.upper(), classes=f"tc-priority-{priority}")
        if category:
            yield Label(category, classes="tc-category")

    def on_click(self, event: events.Click) -> None:
        cb = self.query_one(Checkbox)
        if event.widget != cb:
            cb.value = not cb.value


class AgenticTesterApp(App):
    CSS = APP_CSS
    TITLE = "Agentic Tester"
    SUB_TITLE = "Test Executor"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("a", "select_all", "Select All"),
        Binding("d", "deselect_all", "Deselect All"),
        Binding("r", "run_tests", "Run Selected"),
    ]

    def __init__(self, settings: Optional[Settings] = None, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings or get_settings()
        self.firebase: Optional[FirebaseClient] = None
        self.test_cases_data: list[dict] = []
        self.execution_running = False
        self.mcp_client = create_mcp_client()
        self.inference_agent = InferenceAgent(self.settings)

    def compose(self) -> ComposeResult:
        yield Header()

        # --- Everything in one Vertical so layout is predictable ---
        with Vertical():
            # Config: project + URL
            with Horizontal(id="config-row"):
                yield Label("Project:", classes="config-label")
                yield Select([], prompt="Select project...", id="project-select", allow_blank=True)
                yield Button("Refresh", id="refresh-btn", variant="default", classes="action-btn")
                yield Button("Fetch", id="fetch-btn", variant="primary", classes="action-btn")
                yield Label("URL:", classes="config-label")
                yield Input(value=self.settings.TARGET_URL, placeholder="https://...", id="url-input", classes="config-input")

            # Test list header
            yield Static(
                " [x]  ID             Title                                      Priority",
                id="test-list-header",
            )

            # Scrollable test case list — this is where individual checkboxes appear
            with VerticalScroll(id="test-list"):
                yield Label(
                    "No test cases loaded. Select a project and click Fetch.",
                    id="empty-msg",
                )

            # Actions: compact single row
            with Horizontal(id="actions-row"):
                yield Label("0/0 selected", id="selection-info")
                yield Button("Select All", id="select-all-btn", variant="default", classes="action-btn")
                yield Button("Deselect", id="deselect-all-btn", variant="default", classes="action-btn")
                yield Button("▶ Execute Selected", id="execute-btn", variant="success", disabled=True)

            # Log panels: execution + MCP logs side by side
            with Horizontal(id="log-panels"):
                with Vertical(id="exec-log-panel"):
                    yield Static("EXECUTION LOG", id="exec-log-title", classes="panel-title")
                    yield RichLog(id="exec-log", highlight=True, markup=True, wrap=True)
                with Vertical(id="mcp-log-panel"):
                    yield Static("MCP / APP LOGS", id="mcp-log-title", classes="panel-title")
                    yield RichLog(id="mcp-log", highlight=True, markup=True, wrap=True)

        yield Label("Ready", id="status-bar")
        yield Footer()

    # ─── Lifecycle ────────────────────────────────────────────────

    def on_mount(self) -> None:
        _configure_global_logging()
        audit_log.info("APP    | Started")

        # Set up live MCP log panel — route all Python logging here
        mcp_log = self.query_one("#mcp-log", RichLog)
        mcp_log.write("[bold cyan]MCP & App Logs[/] — streaming live...")
        log_handler = RichLogHandler(mcp_log)
        log_handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        root.addHandler(log_handler)
        root.setLevel(logging.DEBUG)

        self.query_one("#exec-log", RichLog).write("Waiting for test execution...")
        self._init_firebase()
        if self.firebase and self.firebase.is_connected:
            self._load_projects()
        else:
            self._try_local_fallback()

    def _init_firebase(self) -> None:
        try:
            self.firebase = FirebaseClient(
                credentials_path=self.settings.FIREBASE_CREDENTIALS_PATH,
                project_id=self.settings.FIREBASE_PROJECT_ID,
            )
            if self.firebase.is_connected:
                self._set_status("Firebase connected")
            else:
                self._set_status("Firebase unavailable")
        except Exception as e:
            logger.error(f"Firebase init: {e}")
            self._set_status("Firebase error")

    def _try_local_fallback(self) -> None:
        root = Path(__file__).resolve().parent.parent.parent
        files = list(root.glob("*_test_cases.json")) + list(root.glob("sample_test_cases.json"))
        if files:
            self._do_load_local(files[0])
        else:
            self._set_status("No data sources")

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-bar", Label).update(msg)

    def _update_selection_count(self) -> None:
        total = selected = 0
        for cb in self.query("Checkbox"):
            if str(cb.id).startswith("cb-"):
                total += 1
                if cb.value:
                    selected += 1
        self.query_one("#selection-info", Label).update(f"{selected}/{total} selected")
        self.query_one("#execute-btn", Button).disabled = selected == 0 or self.execution_running

    def _render_test_cases(self, test_cases: list[dict], source: str) -> None:
        test_list = self.query_one("#test-list", VerticalScroll)
        for row in self.query("TestCaseRow"):
            row.remove()
        empty_msg = self.query_one("#empty-msg", Label)

        if not test_cases:
            empty_msg.update(f"No test cases from {source}.")
            empty_msg.styles.display = "block"
        else:
            empty_msg.styles.display = "none"
            self.test_cases_data = test_cases
            for tc in test_cases:
                test_list.mount(TestCaseRow(tc))
            self._set_status(f"{len(test_cases)} tests loaded from {source}")
            self._update_selection_count()

    # ─── Events ───────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "refresh-btn":
            self._load_projects()
        elif bid == "fetch-btn":
            self._fetch_for_project()
        elif bid == "select-all-btn":
            self.action_select_all()
        elif bid == "deselect-all-btn":
            self.action_deselect_all()
        elif bid == "execute-btn":
            self.action_run_tests()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if str(event.checkbox.id).startswith("cb-"):
            self._update_selection_count()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "project-select" and event.value != Select.BLANK:
            self._do_fetch(str(event.value))

    def _fetch_for_project(self) -> None:
        sel = self.query_one("#project-select", Select)
        if sel.value != Select.BLANK:
            self._do_fetch(str(sel.value))

    def action_select_all(self) -> None:
        for cb in self.query("Checkbox"):
            if str(cb.id).startswith("cb-"):
                cb.value = True
        self._update_selection_count()

    def action_deselect_all(self) -> None:
        for cb in self.query("Checkbox"):
            if str(cb.id).startswith("cb-"):
                cb.value = False
        self._update_selection_count()

    def action_run_tests(self) -> None:
        if not self.execution_running:
            self._do_execute()

    # ─── Workers ──────────────────────────────────────────────────

    @work(exclusive=True)
    async def _load_projects(self) -> None:
        if not self.firebase or not self.firebase.is_connected:
            return
        self._set_status("Loading projects...")
        sel = self.query_one("#project-select", Select)
        try:
            pids = await self.firebase.fetch_project_ids()
            if pids:
                sel.set_options([(p, p) for p in pids])
                sel.prompt = "Select project..."
                self._set_status(f"{len(pids)} project(s)")
                if len(pids) == 1:
                    sel.value = pids[0]
            else:
                sel.set_options([])
                self._set_status("No projects")
        except Exception as e:
            self._set_status(f"Error: {e}")

    @work(exclusive=True)
    async def _do_load_local(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tcs = data.get("test_cases", data if isinstance(data, list) else [data])
            if isinstance(data, dict) and data.get("target_url"):
                self.query_one("#url-input", Input).value = data["target_url"]
            if isinstance(data, dict) and data.get("project_id"):
                sel = self.query_one("#project-select", Select)
                pid = data["project_id"]
                sel.set_options([(pid, pid)])
                sel.value = pid
            self._render_test_cases(tcs, path.name)
        except Exception as e:
            self._set_status(f"Error: {e}")

    @work(exclusive=True)
    async def _do_fetch(self, project_id: str) -> None:
        if not self.firebase or not self.firebase.is_connected:
            return
        self._set_status(f"Fetching '{project_id}'...")
        self.query_one("#empty-msg", Label).styles.display = "none"
        for row in self.query("TestCaseRow"):
            row.remove()
        try:
            tcs = await self.firebase.fetch_test_cases(project_id)
            self._render_test_cases(tcs, f"firebase:{project_id}")
        except Exception as e:
            self.query_one("#empty-msg", Label).update(f"Error: {e}")
            self.query_one("#empty-msg", Label).styles.display = "block"
            self._set_status(f"Error: {e}")

    @work(exclusive=True)
    async def _do_execute(self) -> None:
        self.execution_running = True
        btn = self.query_one("#execute-btn", Button)
        btn.disabled = True
        btn.label = "Running..."

        elog = self.query_one("#exec-log", RichLog)
        elog.clear()

        etitle = self.query_one("#exec-log-title", Static)
        etitle.update("EXECUTION LOG ─ RUNNING")

        selected_ids = {
            str(cb.id).replace("cb-", "", 1)
            for cb in self.query("Checkbox")
            if str(cb.id).startswith("cb-") and cb.value
        }

        if not selected_ids:
            self._set_status("No tests selected")
            self.execution_running = False
            btn.disabled = False
            btn.label = "▶ Execute Selected"
            return

        selected_data = [tc for tc in self.test_cases_data if tc.get("id") in selected_ids]
        test_cases = [TestCase(**tc) for tc in selected_data]
        target_url = self.query_one("#url-input", Input).value.strip() or self.settings.TARGET_URL
        sel = self.query_one("#project-select", Select)
        project_id = str(sel.value) if sel.value != Select.BLANK else "default"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path("./outputs/executions") / f"run_{ts}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "screenshots").mkdir(exist_ok=True)

        elog.write(f"[bold cyan]Started[/] {datetime.now().strftime('%H:%M:%S')}")
        elog.write(f"URL: {target_url}  |  Tests: {len(test_cases)}")
        elog.write("─" * 50)
        self._set_status(f"Executing {len(test_cases)} tests...")

        try:
            agent = TestExecutorAgent(self.settings, mcp_client=self.mcp_client)
            results = []
            log_lines = []

            for i, tc in enumerate(test_cases, 1):
                self._set_status(f"Test {i}/{len(test_cases)}: {tc.title}")
                elog.write(f"\n[bold]» {i}/{len(test_cases)}:[/] {tc.title}")

                result = await agent.execute_test(tc, target_url=target_url, run_dir=run_dir)
                results.append(result)

                icon = {"passed": "[green]PASS[/]", "failed": "[red]FAIL[/]",
                        "error": "[yellow]ERR[/]", "skipped": "[dim]SKIP[/]"}.get(result.status.value, "?")
                elog.write(f"  {icon} {result.execution_time_ms:.0f}ms")
                if result.error_message:
                    elog.write(f"  [red]{result.error_message[:80]}[/]")
                if result.report_md_path:
                    elog.write(f"  [dim]{Path(result.report_md_path).name}[/]")

                plain = {"passed": "PASS", "failed": "FAIL", "error": "ERR", "skipped": "SKIP"}.get(result.status.value, "?")
                line = f"[{plain}] {tc.id} - {tc.title} ({result.execution_time_ms:.0f}ms)"
                if result.error_message:
                    line += f" | {result.error_message}"
                log_lines.append(line)

                if self.firebase and self.firebase.is_connected:
                    await self.firebase.save_execution_result(result)

            passed = sum(1 for r in results if r.status.value == "passed")
            failed = sum(1 for r in results if r.status.value == "failed")
            errors = sum(1 for r in results if r.status.value == "error")
            total = len(results)

            elog.write(f"\n{'─'*50}")
            elog.write(f"[bold]{passed}/{total} passed, {failed} failed, {errors} errors[/]")
            etitle.update("EXECUTION LOG ─ DONE")

            # Save log
            try:
                lp = run_dir / "execution.log"
                lp.write_text(
                    f"Execution Log - {datetime.now().isoformat()}\n"
                    f"Project: {project_id} | URL: {target_url}\n{'='*60}\n\n"
                    + "\n".join(log_lines) +
                    f"\n\n{'='*60}\nSummary: {passed}/{total} passed\n",
                    encoding="utf-8",
                )
            except Exception:
                pass

            # Inference — output goes into the exec log panel
            if any(r.status.value != "passed" for r in results):
                elog.write("\n[bold yellow]── AI Inference ──[/]")
                self._set_status("Analyzing failures...")

                inf, md = await self.inference_agent.generate_inference_report(
                    "\n".join(log_lines),
                    f"{passed}/{total} passed, {failed} failed, {errors} errors",
                    run_dir,
                )
                elog.write(f"[bold]Root Cause:[/] {inf.get('inferred_reason', '?')}")
                elog.write(f"[bold]Category:[/] {inf.get('category', '?')}")
                elog.write(f"[bold]Severity:[/] {inf.get('severity', '?')}")
                for fix in inf.get("recommended_fixes", []):
                    elog.write(f"  → {fix}")

                if self.firebase and self.firebase.is_connected:
                    await self.firebase.save_execution_audit(
                        execution_id=ts,
                        audit_data={
                            "execution_id": ts, "project_id": project_id,
                            "timestamp": datetime.now().isoformat(),
                            "inferred_reason": inf.get("inferred_reason"),
                            "category": inf.get("category"),
                            "severity": inf.get("severity"),
                            "summary": f"{passed}/{total} passed",
                        },
                    )
            else:
                elog.write("\n[bold green]All tests passed![/]")

            self._set_status(f"Done: {passed}/{total} passed, {failed} failed, {errors} errors")

        except Exception as e:
            self._set_status(f"Error: {e}")
            elog.write(f"\n[red]ERROR: {e}[/]")
            etitle.update("EXECUTION LOG ─ ERROR")

        finally:
            self.execution_running = False
            btn.disabled = False
            btn.label = "▶ Execute Selected"
            self._update_selection_count()


def run_tui(settings: Optional[Settings] = None):
    app = AgenticTesterApp(settings=settings)
    app.run()
