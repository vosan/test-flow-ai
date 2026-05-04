# TestFlowAI

TestFlowAI is a robust framework that uses Selenium to run automation tests on web, where test steps are defined with human-readable language processed by an AI agent.

## Features

- **AI-Powered**: Uses LLMs (OpenAI GPT-4) to interpret natural language steps.
- **Selenium Driven**: Executes atomic actions in the browser based on AI interpretation.
- **Interactive Mode**: Enter steps one-by-one in the terminal.
- **Batch Mode**: Run a group of steps from a `.txt` file.
- **Self-Healing (Conceptual)**: AI analyzes page source to find the best selectors dynamically.

## Installation

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your OpenAI API key in a `.env` file:
   ```
   OPENAI_API_KEY=your_api_key_here
   ```
4. Ensure you have `chromedriver` installed and in your PATH.

## Usage

### Interactive Mode
Run the tool without arguments:
```bash
python -m src.main
```

### Batch Mode
Provide a text file with one step per line:
```bash
python -m src.main tests/sample_test.txt
```

### Commands in Terminal
- Type any natural language step (e.g., `navigate to https://www.google.com`)
- `help`: Show usage instructions.
- `exit` or `quit`: Close the tool.

## Project Structure

- `src/executor.py`: Selenium wrapper for browser actions.
- `src/ai_agent.py`: AI logic for step translation.
- `src/orchestrator.py`: Main logic coordinating AI and Selenium.
- `src/main.py`: CLI entry point.
