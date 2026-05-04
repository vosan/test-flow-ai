from src.executor import SeleniumExecutor
from src.ai_agent import AIAgent
from rich.console import Console

console = Console()

class TestOrchestrator:
    def __init__(self, headless=False):
        self.executor = SeleniumExecutor(headless=headless)
        self.agent = AIAgent()

    def run_step(self, human_step):
        console.print(f"[bold blue]Processing step:[/bold blue] {human_step}")
        
        # 1. Get current state
        page_source = self.executor.get_page_source()
        current_url = self.executor.get_current_url()
        
        # 2. Translate to Selenium command
        command = self.agent.translate_step(human_step, page_source, current_url)
        
        if "error" in command:
            console.print(f"[bold red]AI Error:[/bold red] {command['error']}")
            return False

        console.print(f"[bold green]AI Thought:[/bold green] {command}")
        
        # 3. Execute command
        try:
            result = self.execute_command(command)
            console.print(f"[bold green]Success:[/bold green] {result}")
            return True
        except Exception as e:
            console.print(f"[bold red]Execution Error:[/bold red] {str(e)}")
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
            return self.executor.verify_text(command["text"])
        else:
            raise ValueError(f"Unknown action: {action}")

    def close(self):
        self.executor.quit()
