import sys
import os
from src.orchestrator import TestOrchestrator
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()

def show_help():
    help_text = """
    [bold cyan]TestFlowAI Commands:[/bold cyan]
    
    - [italic]Any natural language step[/italic]: (e.g., 'navigate to google.com', 'click the search button')
    - [bold]help[/bold]: Show this help message
    - [bold]exit[/bold] or [bold]quit[/bold]: Close the tool
    
    [bold cyan]Usage:[/bold cyan]
    
    1. [bold]Interactive Mode[/bold]: Run without arguments to enter step-by-step mode.
    2. [bold]Batch Mode[/bold]: Provide a .txt file path as an argument to run a group of steps.
       Example: [italic]python src/main.py tests/login.txt[/italic]
    """
    console.print(Panel(help_text, title="TestFlowAI Help", expand=False))

def interactive_mode(orchestrator):
    console.print("[bold green]Welcome to TestFlowAI Interactive Mode![/bold green]")
    console.print("Type 'help' for instructions or 'exit' to quit.")
    
    while True:
        step = Prompt.ask("[bold yellow]Enter step[/bold yellow]")
        
        if step.lower() in ['exit', 'quit']:
            break
        elif step.lower() == 'help':
            show_help()
            continue
        elif not step.strip():
            continue
            
        orchestrator.run_step(step)

def batch_mode(orchestrator, file_path):
    if not os.path.exists(file_path):
        console.print(f"[bold red]Error:[/bold red] File {file_path} not found.")
        return

    with open(file_path, 'r') as f:
        steps = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    console.print(f"[bold green]Starting batch mode with {len(steps)} steps...[/bold green]")
    for step in steps:
        success = orchestrator.run_step(step)
        if not success:
            console.print("[bold red]Stopping execution due to error.[/bold red]")
            break

def main():
    console.print(Panel("[bold magenta]TestFlowAI[/bold magenta]\n[italic]AI-Powered Web Automation[/italic]", expand=False))
    
    orchestrator = None
    try:
        # We use headless=True by default in this environment as we might not have a display
        # In a real local setup, users might want to see the browser.
        orchestrator = TestOrchestrator(headless=True)
        
        if len(sys.argv) > 1:
            batch_mode(orchestrator, sys.argv[1])
        else:
            interactive_mode(orchestrator)
            
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Exiting...[/bold yellow]")
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {str(e)}")
    finally:
        if orchestrator:
            orchestrator.close()

if __name__ == "__main__":
    main()
