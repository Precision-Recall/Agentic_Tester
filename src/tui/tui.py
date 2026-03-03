"""
Agentic Tester — Interactive Terminal UI (Textual)

Fetches test cases from Firebase Firestore, lets users pick a project from a
dropdown, select/deselect individual tests, configure the target URL, and
execute with live feedback.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Select,
    Static,
)

from src.config import get_settings, Settings
from src.models.test_case import TestCase, TestSuite
from src.storage.firebase_client import FirebaseClient
from src.executor.agent import TestExecutorAgent

logger = logging.getLogger(__name__)

# ─── Log Configuration ───────────────────────────────────────────────

def _configure_global_logging() -> None:
    """Redirect all logs to file and remove terminal handlers to keep TUI clean."""
    root_logger = logging.getLogger()
    
    # Create log directory
    log_dir = Path("./outputs")
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # File handler for all logs
    file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    
    # Remove existing handlers (including terminal/console)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.INFO)

# ─── Audit Logger (file-based) ────────────────────────────────────────

def _setup_audit_logger() -> logging.Logger:
    """Set up a file-based audit logger for TUI actions."""
    audit = logging.getLogger("tui.audit")
    audit.setLevel(logging.INFO)
    if not audit.handlers:
        from pathlib import Path as _P
        log_dir = _P("./outputs")
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "tui_audit.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        audit.addHandler(fh)
    return audit

audit_log = _setup_audit_logger()

# ─── Custom CSS ───────────────────────────────────────────────────────

APP_CSS = """
Screen {
    background: $surface;
}

#app-title {
    dock: top;
    text-align: center;
    padding: 1 2;
    background: $accent;
    color: $text;
    text-style: bold;
    width: 100%;
}

#config-panel {
    height: auto;
    padding: 1 2;
    background: $panel;
    border: solid $accent;
    margin: 0 1;
}

.config-row {
    height: 3;
    margin-bottom: 1;
}

.config-label {
    width: 16;
    padding: 1 1 0 0;
    text-style: bold;
}

.config-input {
    width: 1fr;
}

#project-select {
    width: 1fr;
}

#refresh-btn {
    width: auto;
    margin-left: 1;
    min-width: 12;
}

#fetch-btn {
    width: auto;
    margin-left: 1;
    min-width: 16;
}

#test-cases-panel {
    margin: 0 1;
    border: solid $accent;
    height: 1fr;
}

#test-cases-header {
    dock: top;
    height: 3;
    padding: 1 2;
    background: $accent 20%;
    text-style: bold;
}

#test-list {
    height: 1fr;
    padding: 0 1;
}

#empty-msg {
    text-align: center;
    padding: 3 0;
    color: $text-muted;
    text-style: italic;
    width: 100%;
}

#loading-container {
    align: center middle;
    height: auto;
    padding: 2;
    display: none;
}

.tc-checkbox {
    width: auto;
}

.tc-id {
    width: 16;
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

#actions-panel {
    height: auto;
    padding: 1 2;
    margin: 0 1;
    background: $panel;
    border: solid $accent;
}

#selection-info {
    width: 1fr;
    padding: 1 0;
}

#execute-btn {
    margin-left: 2;
}

#status-bar {
    dock: bottom;
    height: 3;
    padding: 1 2;
    background: $accent 15%;
}

.action-btn {
    margin-right: 1;
}

#results-panel {
    margin: 0 1;
    border: solid $accent;
    height: auto;
    max-height: 12;
    display: none;
    padding: 1 2;
}

#results-title {
    text-style: bold;
    padding-bottom: 1;
}

.result-pass {
    color: green;
}

.result-fail {
    color: red;
}

.result-error {
    color: yellow;
}
"""


class TestCaseRow(Horizontal):
    """A single test case row with a checkbox."""

    DEFAULT_CSS = """
    TestCaseRow {
        height: 3;
        padding: 0 1;
    }
    TestCaseRow:hover {
        background: $accent 10%;
    }
    """

    def __init__(self, tc_data: dict, **kwargs):
        super().__init__(**kwargs)
        self.tc_data = tc_data
        self.tc_id = tc_data.get("id", "???")

    def compose(self) -> ComposeResult:
        tc = self.tc_data
        priority = tc.get("priority", "medium")
        category = tc.get("category", "???")
        title = tc.get("title", "Untitled")

        yield Checkbox(
            "",
            value=False,  # Force manual selection or 'Select All'
            id=f"cb-{self.tc_id}",
            classes="tc-checkbox",
        )
        yield Label(f" {self.tc_id}", classes="tc-id")
        yield Label(f" {title}", classes="tc-title")
        yield Label(
            f" {priority.upper()}",
            classes=f"tc-priority-{priority}",
        )
        yield Label(f" {category}", classes="tc-category")


class AgenticTesterApp(App):
    """Interactive TUI for the Agentic Tester."""

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

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical():
            yield Label(
                "[>>] Agentic Tester -- Test Executor",
                id="app-title",
            )

            # Config panel — simplified: dropdown + URL
            with Container(id="config-panel"):
                with Horizontal(classes="config-row"):
                    yield Label("Project:", classes="config-label")
                    yield Select(
                        [],
                        prompt="Loading projects...",
                        id="project-select",
                        allow_blank=True,
                    )
                    yield Button(
                        "[~] Refresh",
                        id="refresh-btn",
                        variant="default",
                    )
                    yield Button(
                        "[v] Fetch Tests",
                        id="fetch-btn",
                        variant="primary",
                    )
                with Horizontal(classes="config-row"):
                    yield Label("Target URL:", classes="config-label")
                    yield Input(
                        value=self.settings.TARGET_URL,
                        placeholder="https://example.com",
                        id="url-input",
                        classes="config-input",
                    )

            # Test cases panel
            with Container(id="test-cases-panel"):
                yield Label(
                    "  ID               Title                              Priority  Category",
                    id="test-cases-header",
                )
                with Container(id="loading-container"):
                    yield LoadingIndicator()
                    yield Label("  Loading test cases...")
                with VerticalScroll(id="test-list"):
                    yield Label(
                        "No test cases loaded.\n\n"
                        "Select a project from the dropdown above to load tests.",
                        id="empty-msg",
                    )

            # Actions panel
            with Container(id="actions-panel"):
                with Horizontal():
                    yield Label("Selected: 0/0", id="selection-info")
                    yield Button(
                        "[+] Select All",
                        id="select-all-btn",
                        variant="default",
                        classes="action-btn",
                    )
                    yield Button(
                        "[-] Deselect All",
                        id="deselect-all-btn",
                        variant="default",
                        classes="action-btn",
                    )
                    yield Button(
                        "[>] Execute Selected",
                        id="execute-btn",
                        variant="success",
                        disabled=True,
                    )

            # Results panel (hidden until execution)
            with Container(id="results-panel"):
                yield Label("--- Execution Results ---", id="results-title")
                yield Static("", id="results-content")

        yield Footer()
        yield Label("Status: Ready -- Connecting to Firebase...", id="status-bar")

    def on_mount(self) -> None:
        """Initialize Firebase and load projects on mount."""
        _configure_global_logging()
        audit_log.info("APP    | Started TUI")
        self._init_firebase()
        if self.firebase and self.firebase.is_connected:
            self._load_projects()
        else:
            # Try loading from local JSON as fallback
            self._try_local_fallback()

    def _init_firebase(self) -> None:
        """Initialize the Firebase client."""
        try:
            self.firebase = FirebaseClient(
                credentials_path=self.settings.FIREBASE_CREDENTIALS_PATH,
                project_id=self.settings.FIREBASE_PROJECT_ID,
            )
            if self.firebase.is_connected:
                audit_log.info("INIT   | Firebase connected")
                self._set_status("[OK] Firebase connected -- Loading projects...")
            else:
                self._set_status(
                    "[!] Firebase not connected -- Loading from local files..."
                )
        except Exception as e:
            logger.error(f"Firebase init failed: {e}")
            self._set_status("[!] Firebase unavailable -- Loading from local files...")

    def _try_local_fallback(self) -> None:
        """Try to load test cases from local JSON files as fallback."""
        project_root = Path(__file__).resolve().parent.parent.parent
        json_files = list(project_root.glob("*_test_cases.json")) + list(
            project_root.glob("sample_test_cases.json")
        )

        if json_files:
            # Load the first found file
            self._do_load_local_file(json_files[0])
        else:
            select = self.query_one("#project-select", Select)
            select.set_options([])
            select.prompt = "No projects found"
            self._set_status("[!] No Firebase connection and no local test files found")

    def _set_status(self, msg: str) -> None:
        """Update the status bar."""
        status = self.query_one("#status-bar", Label)
        status.update(f"Status: {msg}")

    def _update_selection_count(self) -> None:
        """Update the selection info label."""
        checkboxes = self.query("Checkbox")
        total = 0
        selected = 0
        for cb in checkboxes:
            if str(cb.id).startswith("cb-"):
                total += 1
                if cb.value:
                    selected += 1

        info = self.query_one("#selection-info", Label)
        info.update(f"Selected: {selected}/{total}")

        execute_btn = self.query_one("#execute-btn", Button)
        execute_btn.disabled = selected == 0 or self.execution_running

    def _render_test_cases(self, test_cases: list[dict], source: str) -> None:
        """Render test case rows in the list."""
        test_list = self.query_one("#test-list", VerticalScroll)

        # Clear existing rows
        for row in self.query("TestCaseRow"):
            row.remove()

        empty_msg = self.query_one("#empty-msg", Label)

        if not test_cases:
            empty_msg.update(f"No test cases found from {source}.")
            empty_msg.styles.display = "block"
            self._set_status(f"[!] No test cases found from {source}")
        else:
            empty_msg.styles.display = "none"
            self.test_cases_data = test_cases
            for tc in test_cases:
                row = TestCaseRow(tc)
                test_list.mount(row)

            self._set_status(
                f"[OK] Loaded {len(test_cases)} test cases from {source} "
                "-- Select tests and press R to execute"
            )
            self._update_selection_count()

    # ─── Button handlers ──────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        audit_log.info(f"BUTTON | {btn_id}")

        if btn_id == "refresh-btn":
            self._load_projects()
        elif btn_id == "fetch-btn":
            self._fetch_for_selected_project()
        elif btn_id == "select-all-btn":
            self.action_select_all()
        elif btn_id == "deselect-all-btn":
            self.action_deselect_all()
        elif btn_id == "execute-btn":
            self.action_run_tests()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Update count when any checkbox changes."""
        self._update_selection_count()

    def on_select_changed(self, event: Select.Changed) -> None:
        """When user picks a project from the dropdown, auto-fetch its test cases."""
        if event.select.id == "project-select" and event.value != Select.BLANK:
            project_id = str(event.value)
            audit_log.info(f"SELECT | project={project_id}")
            self._do_fetch(project_id)

    # ─── Actions ──────────────────────────────────────────────────

    def _fetch_for_selected_project(self) -> None:
        """Fetch test cases for the currently selected project (Fetch Tests button)."""
        select = self.query_one("#project-select", Select)
        if select.value == Select.BLANK:
            self._set_status("[!] Select a project first, then click Fetch Tests")
            return
        project_id = str(select.value)
        audit_log.info(f"FETCH  | project={project_id} (manual trigger)")
        self._do_fetch(project_id)

    def action_select_all(self) -> None:
        """Select all test case checkboxes."""
        for cb in self.query("Checkbox"):
            if str(cb.id).startswith("cb-"):
                cb.value = True
        self._update_selection_count()

    def action_deselect_all(self) -> None:
        """Deselect all test case checkboxes."""
        for cb in self.query("Checkbox"):
            if str(cb.id).startswith("cb-"):
                cb.value = False
        self._update_selection_count()

    def action_run_tests(self) -> None:
        """Trigger test execution."""
        if not self.execution_running:
            self._do_execute()

    # ─── Async workers ────────────────────────────────────────────

    @work(exclusive=True)
    async def _load_projects(self) -> None:
        """Fetch project IDs from Firebase and populate the dropdown."""
        if not self.firebase or not self.firebase.is_connected:
            self._set_status("🔴 Firebase not connected")
            return

        self._set_status("(...) Loading projects from Firebase...")
        select = self.query_one("#project-select", Select)

        try:
            project_ids = await self.firebase.fetch_project_ids()

            if project_ids:
                options = [(pid, pid) for pid in project_ids]
                select.set_options(options)
                select.prompt = "Select a project..."
                self._set_status(
                    f"[OK] Found {len(project_ids)} project(s) -- "
                    "Select one to load test cases"
                )
                # Auto-select if there's only one project
                if len(project_ids) == 1:
                    select.value = project_ids[0]
            else:
                select.set_options([])
                select.prompt = "No projects found"
                self._set_status("[!] No test projects found in Firebase")

        except Exception as e:
            select.set_options([])
            select.prompt = "Error loading projects"
            self._set_status(f"[ERR] Failed to load projects: {e}")

    @work(exclusive=True)
    async def _do_load_local_file(self, file_path: Path) -> None:
        """Load test cases from a local JSON file."""
        self._set_status(f"(...) Loading test cases from {file_path.name}...")

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))

            if "test_cases" in data:
                test_cases = data["test_cases"]
                if data.get("target_url"):
                    url_input = self.query_one("#url-input", Input)
                    url_input.value = data["target_url"]
                # Set project in dropdown
                if data.get("project_id"):
                    select = self.query_one("#project-select", Select)
                    pid = data["project_id"]
                    select.set_options([(pid, pid)])
                    select.value = pid
            elif isinstance(data, list):
                test_cases = data
            else:
                test_cases = [data]

            self._render_test_cases(test_cases, f"file: {file_path.name}")

        except Exception as e:
            self._set_status(f"[ERR] Error loading file: {e}")

    @work(exclusive=True)
    async def _do_fetch(self, project_id: str) -> None:
        """Fetch test cases from Firebase for the selected project."""
        if not self.firebase or not self.firebase.is_connected:
            self._set_status("🔴 Firebase not connected")
            return

        # Show loading state
        self._set_status(f"(...) Fetching test cases for '{project_id}'...")
        loading = self.query_one("#loading-container")
        loading.styles.display = "block"
        empty_msg = self.query_one("#empty-msg", Label)
        empty_msg.styles.display = "none"

        # Clear existing rows
        for row in self.query("TestCaseRow"):
            row.remove()

        try:
            test_cases = await self.firebase.fetch_test_cases(project_id)
            loading.styles.display = "none"
            self._render_test_cases(test_cases, f"firebase: {project_id}")

        except Exception as e:
            loading.styles.display = "none"
            empty_msg.update(f"Error fetching test cases: {e}")
            empty_msg.styles.display = "block"
            self._set_status(f"[ERR] Fetch failed: {e}")

    @work(exclusive=True)
    async def _do_execute(self) -> None:
        """Execute selected test cases (background worker)."""
        self.execution_running = True
        execute_btn = self.query_one("#execute-btn", Button)
        execute_btn.disabled = True
        execute_btn.label = "(...) Running..."

        # Gather selected test case IDs
        selected_ids = set()
        for cb in self.query("Checkbox"):
            if str(cb.id).startswith("cb-") and cb.value:
                tc_id = str(cb.id).replace("cb-", "", 1)
                selected_ids.add(tc_id)

        if not selected_ids:
            self._set_status("[!] No test cases selected")
            self.execution_running = False
            execute_btn.disabled = False
            execute_btn.label = "▶  Execute Selected"
            return

        # Build TestCase list from selected
        selected_data = [
            tc for tc in self.test_cases_data
            if tc.get("id") in selected_ids
        ]
        test_cases = [TestCase(**tc) for tc in selected_data]

        url_input = self.query_one("#url-input", Input)
        target_url = url_input.value.strip() or self.settings.TARGET_URL

        select = self.query_one("#project-select", Select)
        project_id = str(select.value) if select.value != Select.BLANK else "default"

        suite = TestSuite(
            id=f"tui-{project_id}",
            project_id=project_id,
            test_cases=test_cases,
            target_url=target_url,
        )

        self._set_status(
            f"(...) Executing {len(test_cases)} test cases against {target_url}..."
        )

        # Show results panel
        results_panel = self.query_one("#results-panel")
        results_panel.styles.display = "block"
        results_content = self.query_one("#results-content", Static)
        results_content.update("Running tests...\n")

        try:
            agent = TestExecutorAgent(self.settings)
            results_lines = []

            # Execute each test individually for live feedback
            for i, test_case in enumerate(test_cases, 1):
                self._set_status(
                    f"(...) Running test {i}/{len(test_cases)}: {test_case.title}"
                )
                result = await agent.execute_test(test_case, target_url=target_url)

                status_icon = {
                    "passed": "[PASS]",
                    "failed": "[FAIL]",
                    "error": "[ERR]",
                    "skipped": "[SKIP]",
                }.get(result.status.value, "[?]")

                line = (
                    f"{status_icon} {test_case.id} — {test_case.title} "
                    f"({result.execution_time_ms:.0f}ms)"
                )
                if result.error_message:
                    line += f"\n   └─ {result.error_message}"

                results_lines.append(line)
                results_content.update("\n".join(results_lines))

                # Persist to Firebase if connected
                if self.firebase and self.firebase.is_connected:
                    await self.firebase.save_execution_result(result)

            # Summary
            passed = sum(1 for l in results_lines if l.startswith("[PASS]"))
            failed = sum(1 for l in results_lines if l.startswith("[FAIL]"))
            errors = sum(1 for l in results_lines if l.startswith("[ERR]"))
            total = len(results_lines)

            # ─── Save Execution Log to File ───────────────────────────
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                run_dir = Path("./outputs/executions") / f"run_{timestamp}"
                run_dir.mkdir(parents=True, exist_ok=True)
                
                log_path = run_dir / "execution.log"
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"Agentic Tester - Execution Log\n")
                    f.write(f"Timestamp: {datetime.now().isoformat()}\n")
                    f.write(f"Project: {project_id}\n")
                    f.write(f"Target URL: {target_url}\n")
                    f.write(f"{'='*60}\n\n")
                    f.write("\n".join(results_lines))
                    f.write(f"\n\n{'='*60}\n")
                    f.write(f"Summary: {passed}/{total} passed, {failed} failed, {errors} errors\n")
                
                audit_log.info(f"EXEC   | Saved execution log to {log_path}")
            except Exception as log_err:
                audit_log.error(f"EXEC   | Failed to save execution log: {log_err}")

            summary_line = (
                f"\n{'─' * 50}\n"
                f"Results: {passed}/{total} passed, "
                f"{failed} failed, {errors} errors"
            )
            results_lines.append(summary_line)
            results_content.update("\n".join(results_lines))

            self._set_status(
                f"[OK] Done: {passed}/{total} passed, {failed} failed, {errors} errors"
            )

        except Exception as e:
            self._set_status(f"[ERR] Execution error: {e}")
            results_content.update(f"Execution failed: {e}")

        finally:
            self.execution_running = False
            execute_btn.disabled = False
            execute_btn.label = "▶  Execute Selected"
            self._update_selection_count()


def run_tui(settings: Optional[Settings] = None):
    """Launch the TUI app."""
    app = AgenticTesterApp(settings=settings)
    app.run()
