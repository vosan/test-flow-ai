from src.executor import SeleniumExecutor
from src.ai_agent import AIAgent
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
        self.selenium_retries = self._get_int_env("SELENIUM_RETRIES", 10, min_v=1, max_v=100)
        self.ai_retries = self._get_int_env("AI_RETRIES", 2, min_v=0, max_v=10)

    def run_step(self, human_step):
        console.print(f"[bold blue]Processing step:[/bold blue] {human_step}")
        
        # Enforce quoting rule for exact text verification steps
        step_lower = human_step.strip().lower()
        if step_lower.startswith("verify") or step_lower.startswith("check"):
            if not re.search(r"^(?:verify|check)\s+(['\"])(.*?)\1\s*$", human_step.strip(), flags=re.IGNORECASE):
                console.print(
                    "[bold red]Input Error:[/bold red] Exact text must be surrounded with quotes. "
                    "Example: verify \"Google\" or verify 'Google'"
                )
                return False

        # Outer loop: AI planning attempts
        last_error = None
        for ai_attempt in range(1, self.ai_retries + 2):  # total attempts = 1 initial + ai_retries re-plans
            if ai_attempt > 1:
                console.print(
                    f"[yellow]Re-asking AI for a new plan (AI attempt {ai_attempt}/{self.ai_retries})...[/yellow]"
                )
            # 1. Get fresh current state for each AI attempt
            page_source = self.executor.get_page_source()
            current_url = self.executor.get_current_url()

            # 2. Translate to Selenium command
            command = self.agent.translate_step(human_step, page_source, current_url)

            # Always show AI Thought, even if it contains an error
            thought_color = "yellow" if "error" in command else "green"
            console.print(f"[bold {thought_color}]AI Thought:[/bold {thought_color}] {command}")

            if "error" in command:
                last_error = command.get("error")
                console.print(f"[bold red]AI Error:[/bold red] {last_error}")
                # If AI failed to even produce a plan, try next AI attempt if available
                if ai_attempt <= self.ai_retries:
                    continue
                else:
                    return False

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
            if ai_attempt > self.ai_retries:
                # No more AI retries left
                break

        # Final failure
        console.print(
            f"[bold red]Step failed after {self.ai_retries + 1} AI attempt(s) "
            f"and up to {self.selenium_retries} Selenium attempt(s) each. Last error: {last_error}[/bold red]"
        )
        return False

    def execute_command(self, command):
        action = command.get("action")
        if action == "navigate":
            return self.executor.navigate(command["url"])
        elif action == "click":
            return self.executor.click(command["selector"])
        elif action == "type":
            return self.executor.type_text(command["selector"], command["value"])
        elif action == "press_key":
            return self.executor.press_key(command["key"])
        elif action == "verify":
            text = command.get("text", "")
            # In case the AI returns quoted text, strip surrounding quotes
            if isinstance(text, str) and len(text) >= 2 and (
                (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'"))
            ):
                text = text[1:-1]
            return self.executor.verify_text(text)
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
