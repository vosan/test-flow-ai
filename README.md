# TestFlowAI

TestFlowAI is a robust framework that uses Selenium to run automation tests on web, where test steps are defined with human-readable language processed by an AI agent.

## Features

- **AI-Powered, Provider-Agnostic**: Works with OpenAI and most OpenAI-compatible APIs (OpenRouter, Groq, DeepSeek, Together/Fireworks) and even local Ollama. Also supports Azure OpenAI. Pick the model/provider you prefer via simple environment variables.
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
3. Configure your preferred AI provider in a `.env` file. Quick examples:

   - OpenAI (default):
     ```
     OPENAI_API_KEY=your_openai_key
     # optional overrides
     LLM_MODEL=gpt-4o
     ```

   - OpenAI‑compatible providers (just set a base URL and a key):
     - OpenRouter
       ```
       LLM_BASE_URL=https://openrouter.ai/api/v1
       LLM_API_KEY=your_openrouter_key
       LLM_MODEL=meta-llama/Meta-Llama-3.1-8B-Instruct
       ```
     - Groq (OpenAI-compatible endpoint)
       ```
       LLM_BASE_URL=https://api.groq.com/openai/v1
       LLM_API_KEY=your_groq_key
       LLM_MODEL=llama-3.1-8b-instant
       ```
     - DeepSeek
       ```
       LLM_BASE_URL=https://api.deepseek.com/v1
       LLM_API_KEY=your_deepseek_key
       LLM_MODEL=deepseek-chat
       ```
     - Local Ollama (no key usually required)
       ```
       LLM_BASE_URL=http://localhost:11434/v1
       LLM_API_KEY=EMPTY
       LLM_MODEL=llama3.1:8b-instruct
       ```

   - Azure OpenAI:
     ```
     AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
     AZURE_OPENAI_API_KEY=your_azure_key
     AZURE_OPENAI_API_VERSION=2024-02-15-preview
     # Use your Azure deployment name as the model
     LLM_MODEL=gpt-4o
     ```
4. Ensure you have Google Chrome/Chromium installed. With Selenium ≥ 4.6, Selenium Manager will automatically download and manage the correct ChromeDriver — no manual setup required.

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

### Browser visibility (headless vs visible)
- By default, TestFlowAI launches a visible Chrome window so you can observe execution.
- To run in headless mode (useful for CI/servers without a display), set the environment variable `HEADLESS=true`.
  - Examples:
    - macOS/Linux: `HEADLESS=true python -m src.main`
    - Windows (PowerShell): `$env:HEADLESS='true'; python -m src.main`
  - You can also put `HEADLESS=true` in your `.env` file.

## Project Structure

- `src/executor.py`: Selenium wrapper for browser actions.
- `src/ai_agent.py`: Provider-agnostic AI logic for step translation (OpenAI, OpenAI-compatible APIs, Azure, Ollama).
- `src/orchestrator.py`: Main logic coordinating AI and Selenium.
- `src/main.py`: CLI entry point.

## Choosing a cost-efficient model/provider

Here are some budget-friendly options that work well with TestFlowAI. Actual prices change frequently; check the provider’s pricing page.

- Local (no per-token fees):
  - Ollama with small models like Llama 3.1 8B Instruct or Mistral 7B Instruct. Great for quick iterations and offline usage; slightly lower accuracy than larger cloud models.

- OpenAI‑compatible hosted providers:
  - Groq (OpenAI-compatible API) with Llama 3.1 8B variants – very fast and inexpensive for structured tasks.
  - OpenRouter routing to economical models (e.g., Llama 3.x 8B/70B, Mixtral variants). Lets you switch models via a single key.
  - DeepSeek’s chat/instruct models – competitive pricing with strong performance for short prompts.

Tips to control cost and improve reliability:
- Keep prompts short; this tool already truncates page source to reduce tokens.
- Prefer smaller “instruct” models for simple steps; switch to larger models only when necessary.
- If a provider does not support strict JSON output, TestFlowAI will attempt to parse JSON from text—keeping compatibility broad while minimizing retries.
