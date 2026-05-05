from src.executor import SeleniumExecutor
from src.ai_agent import AIAgent
from src.schema import Command as DSLCommand, normalize_legacy
from src.selector_resolver import SelectorResolver
from rich.console import Console
import re
import os
import time

console = Console()

class TestOrchestrator:
    def __init__(self, headless=False):
        self.executor = SeleniumExecutor(headless=headless)
        self.agent = AIAgent()
        self.resolver = SelectorResolver()
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
        # Carry structured re-plan context between AI attempts when selector confidence is low
        ai_replan_context = None
        for ai_attempt in range(1, self.ai_retries + 1):
            if ai_attempt > 1:
                console.print(
                    f"[yellow]Re-asking AI for a new plan (AI attempt {ai_attempt}/{self.ai_retries})...[/yellow]"
                )
            # 1. Get fresh current state for each AI attempt
            page_source = self.executor.get_page_source()
            current_url = self.executor.get_current_url()

            # 2. Translate to command via AI (may be legacy or new DSL)
            command = self.agent.translate_step(human_step, page_source, current_url, replan_context=ai_replan_context)

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
                _validated = DSLCommand.model_validate(command)
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

            # 2.5 Resolve selector with confidence-based decision layer (for click/type only)
            if command.get("action") in {"click", "type"}:
                target = command.get("target")
                # Get a resolver snapshot (use the same page_source/current_url captured for this AI attempt)
                res1 = self.resolver.resolve(target, page_source, current_url, broaden=False)
                sel1 = res1.get("selector")
                conf1 = float(res1.get("confidence") or 0.0)
                console.print(
                    f"[dim]Resolved target -> selector:[/dim] '{target}' -> '{sel1}' (conf {conf1:.2f}; first pass)"
                )
                decision_path = []
                decision_path.append(f"first:{conf1:.2f}")

                # Validate basic selector usability
                unusable = (not sel1) or (sel1 in {"page", "active_element"})
                if unusable:
                    conf1 = 0.0

                # Threshold decision
                if conf1 >= 0.85 and not unusable:
                    console.print(
                        f"[dim]Resolved target -> selector:[/dim] '{target}' -> '{sel1}' (conf {conf1:.2f}; decision accept)"
                    )
                    console.print(
                        f"[dim]Decision path:[/dim] {', '.join(decision_path)} for target '{target}'"
                    )
                    # Clear any previous re-plan context on success
                    ai_replan_context = None
                    command["resolved_selector"] = sel1
                elif conf1 >= 0.60 and conf1 < 0.85 and not unusable:
                    # Retry resolution once with broadened matching
                    res2 = self.resolver.resolve(target, page_source, current_url, broaden=True)
                    sel2 = res2.get("selector")
                    conf2 = float(res2.get("confidence") or 0.0)
                    console.print(
                        f"[dim]Resolved target -> selector:[/dim] '{target}' -> '{sel2}' (conf {conf2:.2f}; broaden)"
                    )
                    if (not sel2) or (sel2 in {"page", "active_element"}):
                        conf2 = 0.0
                    decision_path.append(f"broaden:{conf2:.2f}")
                    if conf2 >= 0.85:
                        console.print(
                            f"[dim]Resolved target -> selector:[/dim] '{target}' -> '{sel2}' (conf {conf2:.2f}; decision accept after broaden)"
                        )
                        console.print(
                            f"[dim]Decision path:[/dim] first:{conf1:.2f}  broaden:{conf2:.2f} (accepted) for target '{target}'"
                        )
                        ai_replan_context = None
                        command["resolved_selector"] = sel2
                    else:
                        # Trigger AI re-plan
                        console.print(
                            f"[yellow]Resolution below confidence threshold after broaden; requesting AI re-plan.[/yellow]"
                        )
                        console.print(
                            f"[dim]Decision path:[/dim] {', '.join(decision_path)} for target '{target}'"
                        )
                        last_error = f"Low selector confidence for target '{target}' (path: {', '.join(decision_path)})"
                        # Provide structured re-plan context to the AI on the next attempt
                        ai_replan_context = {
                            "reason": "low_confidence_selector",
                            "target": target,
                            "attempts": [
                                {"pass": "first", "selector": sel1, "confidence": round(conf1, 4)},
                                {"pass": "broaden", "selector": sel2, "confidence": round(conf2, 4)},
                            ],
                        }
                        # Move to next AI attempt if available
                        if ai_attempt < self.ai_retries:
                            continue
                        else:
                            console.print(
                                f"[bold red]Step failed due to low selector confidence and no AI retries left.[/bold red]"
                            )
                            return False
                else:
                    # conf1 < 0.60 or unusable -> immediate AI re-plan
                    console.print(
                        f"[yellow]Resolution confidence too low ({conf1:.2f}); requesting AI re-plan.[/yellow]"
                    )
                    console.print(
                        f"[dim]Decision path:[/dim] {', '.join(decision_path)} for target '{target}'"
                    )
                    last_error = f"Low selector confidence for target '{target}' (path: {', '.join(decision_path)})"
                    ai_replan_context = {
                        "reason": "low_confidence_selector",
                        "target": target,
                        "attempts": [
                            {"pass": "first", "selector": sel1, "confidence": round(conf1, 4)},
                        ],
                    }
                    if ai_attempt < self.ai_retries:
                        continue
                    else:
                        console.print(
                            f"[bold red]Step failed due to low selector confidence and no AI retries left.[/bold red]"
                        )
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
            # Use pre-resolved selector if available; else fall back to on-demand resolution
            selector = command.get("resolved_selector")
            if selector:
                return self.executor.click(selector)
            # Fallback path (legacy): resolve now with minimal guard
            console.print("[dim]Using legacy on-demand resolution path (no pre-resolved selector available).[/dim]")
            page_source = self.executor.get_page_source()
            current_url = self.executor.get_current_url()
            res = self.resolver.resolve(command["target"], page_source, current_url)
            selector = res.get("selector")
            confidence = float(res.get("confidence") or 0.0)
            console.print(f"[dim]Resolved target -> selector:[/dim] '{command['target']}' -> '{selector}' (conf {confidence:.2f})")
            if not selector or selector in {"page", "active_element"} or confidence < 0.3:
                raise ValueError(f"Could not resolve a usable selector for target '{command['target']}' (confidence {confidence:.2f})")
            return self.executor.click(selector)
        elif action == "type":
            selector = command.get("resolved_selector")
            if selector:
                return self.executor.type_text(selector, command["value"])
            # Fallback legacy resolution
            console.print("[dim]Using legacy on-demand resolution path (no pre-resolved selector available).[/dim]")
            page_source = self.executor.get_page_source()
            current_url = self.executor.get_current_url()
            res = self.resolver.resolve(command["target"], page_source, current_url)
            selector = res.get("selector")
            confidence = float(res.get("confidence") or 0.0)
            console.print(f"[dim]Resolved target -> selector:[/dim] '{command['target']}' -> '{selector}' (conf {confidence:.2f})")
            if not selector or selector in {"page", "active_element"} or confidence < 0.3:
                raise ValueError(f"Could not resolve a usable selector for target '{command['target']}' (confidence {confidence:.2f})")
            return self.executor.type_text(selector, command["value"])
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
