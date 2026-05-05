from src.executor import SeleniumExecutor
from src.ai_agent import AIAgent
from src.schema import Command as DSLCommand, normalize_legacy
from rich.console import Console
import re
import os
import time

console = Console()

class TestOrchestrator:
    def __init__(self, headless=False):
        self.executor = SeleniumExecutor(headless=headless)
        self.agent = AIAgent()
        # Configurable retries
        self.selenium_retries = self._get_int_env("SELENIUM_RETRIES", 5, min_v=1, max_v=100)
        # Note: AI_RETRIES represents the TOTAL number of AI planning attempts (not plus one)
        self.ai_retries = self._get_int_env("AI_RETRIES", 2, min_v=1, max_v=10)

    def run_step(self, human_step):
        console.print(f"[bold blue]Processing step:[/bold blue] {human_step}")
        
        # Enforce quoting rule for exact text verification steps
        step_lower = human_step.strip().lower()
        user_verify_literal = None
        if step_lower.startswith("verify") or step_lower.startswith("check"):
            m_verify = re.search(r"^(?:verify|check)\s+(['\"])(.*?)\1\s*$", human_step.strip(), flags=re.IGNORECASE)
            if not m_verify:
                console.print(
                    "[bold red]Input Error:[/bold red] Exact text must be surrounded with quotes. "
                    "Example: verify \"Google\" or verify 'Google'"
                )
                return False
            # Capture the exact literal inside quotes to enforce verbatim usage later
            user_verify_literal = m_verify.group(2)

        # Outer loop: AI planning attempts (total attempts == self.ai_retries)
        last_error = None
        for ai_attempt in range(1, self.ai_retries + 1):
            if ai_attempt > 1:
                console.print(
                    f"[yellow]Re-asking AI for a new plan (AI attempt {ai_attempt}/{self.ai_retries})...[/yellow]"
                )
            # 1. Get fresh current state for each AI attempt
            page_source = self.executor.get_page_source()
            current_url = self.executor.get_current_url()

            # 2. Translate to command via AI (may be legacy or new DSL)
            command = self.agent.translate_step(human_step, page_source, current_url)

            # Always show AI Thought, even if it contains an error
            thought_color = "yellow" if "error" in command else "green"
            console.print(f"[bold {thought_color}]AI Thought:[/bold {thought_color}] {command}")

            if "error" in command:
                last_error = command.get("error")
                console.print(f"[bold red]AI Error:[/bold red] {last_error}")
                # If AI failed to even produce a plan, try next AI attempt if available
                if ai_attempt < self.ai_retries:
                    continue
                else:
                    return False

            # Normalize legacy schema to new DSL and validate strictly
            try:
                command = normalize_legacy(command)
                # Validate and keep using plain dict to minimize refactor surface
                _validated = DSLCommand.parse_obj(command)
            except Exception as ve:
                last_error = f"Invalid command schema: {ve}"
                console.print(f"[bold red]Schema Error:[/bold red] {last_error}")
                if ai_attempt < self.ai_retries:
                    continue
                else:
                    return False

            # If this is a verify/check step, enforce that the text exactly matches the user's quoted literal
            if user_verify_literal is not None and command.get("action") == "verify":
                assertion = command.get("assertion") or {}
                ai_expected = assertion.get("expected", "")
                # Unquote AI expected if it sent quotes back
                if isinstance(ai_expected, str) and len(ai_expected) >= 2 and (
                    (ai_expected.startswith('"') and ai_expected.endswith('"')) or (ai_expected.startswith("'") and ai_expected.endswith("'"))
                ):
                    ai_expected_unquoted = ai_expected[1:-1]
                else:
                    ai_expected_unquoted = ai_expected
                if ai_expected_unquoted != user_verify_literal:
                    console.print(
                        f"[yellow]Using exact quoted text from user instead of AI output: '{user_verify_literal}'[/yellow]"
                    )
                # Overwrite with the exact literal from the user (no surrounding quotes)
                assertion["type"] = assertion.get("type") or "contains_text"
                assertion["expected"] = user_verify_literal
                command["assertion"] = assertion

            # 3. Execute command with Selenium-level retries
            success = False
            sel_error = None
            for sel_attempt in range(1, self.selenium_retries + 1):
                try:
                    result = self.execute_command(command)
                    # If it succeeded after multiple attempts, reflect that
                    if sel_attempt > 1 or ai_attempt > 1:
                        console.print(
                            f"[cyan]Recovered after AI attempt {ai_attempt}/{self.ai_retries} "
                            f"and Selenium attempt {sel_attempt}/{self.selenium_retries}.[/cyan]"
                        )
                    console.print(f"[bold green]Success:[/bold green] {result}")
                    success = True
                    break
                except Exception as e:
                    sel_error = e
                    # Only reflect retry info if more than one attempt is happening
                    if sel_attempt > 1:
                        console.print(
                            f"[yellow]Selenium retry {sel_attempt}/{self.selenium_retries} failed: {str(e)}[/yellow]"
                        )
                    # Backoff before next attempt if any remain
                    if sel_attempt < self.selenium_retries:
                        # Exponential backoff capped to 2s
                        delay = min(2.0, 0.1 * (2 ** (sel_attempt - 1)))
                        time.sleep(delay)

            if success:
                return True

            # If we reach here, Selenium failed all attempts for this AI plan
            console.print(
                f"[bold yellow]All Selenium attempts ({self.selenium_retries}) failed for the current AI plan.[/bold yellow]"
            )
            last_error = sel_error
            if ai_attempt >= self.ai_retries:
                # No more AI retries left
                break

        # Final failure
        console.print(
            f"[bold red]Step failed after {self.ai_retries} AI attempt(s) "
            f"and up to {self.selenium_retries} Selenium attempt(s) each. Last error: {last_error}[/bold red]"
        )
        return False

    def execute_command(self, command):
        action = command.get("action")
        if action == "navigate":
            return self.executor.navigate(command["url"])
        elif action == "click":
            return self.executor.click(command["target"])
        elif action == "type":
            return self.executor.type_text(command["target"], command["value"])
        elif action == "press_key":
            return self.executor.press_key(command["key"])
        elif action == "verify":
            assertion = command.get("assertion") or {}
            atype = assertion.get("type")
            expected = assertion.get("expected")
            # Only document-level assertions without selector resolution for now
            if atype == "contains_text":
                if not isinstance(expected, str):
                    raise ValueError("'expected' must be a string for contains_text")
                return self.executor.verify_text(expected)
            elif atype == "equals_text":
                raise NotImplementedError("equals_text assertion is not implemented yet")
            elif atype in {"element_visible", "element_count"}:
                raise NotImplementedError(f"{atype} assertion is not implemented yet")
            else:
                raise ValueError(f"Unknown verify assertion type: {atype}")
        else:
            raise ValueError(f"Unknown action: {action}")

    def _get_int_env(self, name: str, default: int, min_v: int = 0, max_v: int = 1_000_000) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            val = int(raw)
            val = max(min_v, min(max_v, val))
            return val
        except Exception:
            return default

    def close(self):
        self.executor.quit()
