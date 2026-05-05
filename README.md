# TestFlowAI

TestFlowAI is a robust framework that uses Selenium to run automation tests on web, where test steps are defined with human-readable language processed by an AI agent.

## Features

- **AI-Powered, Provider-Agnostic**: Works with OpenAI and most OpenAI-compatible APIs (OpenRouter, Groq, DeepSeek, Together/Fireworks) and even local Ollama. Also supports Azure OpenAI. Pick the model/provider you prefer via simple environment variables.
- **Selenium Driven**: Executes atomic actions in the browser based on AI interpretation.
- **Interactive Mode**: Enter steps one-by-one in the terminal.
- **Batch Mode**: Run a group of steps from a `.txt` file.
- **Self-Healing (Conceptual)**: AI analyzes page source to find the best selectors dynamically.
 - **Privacy-friendly browser session**: Always launches Chrome with a clean temporary profile, password manager disabled, and notifications blocked to avoid pop-ups and data persistence between runs.

## Technical Details

This section summarizes how TestFlowAI is implemented under the hood: core components, data flow, retries, and configuration.

- High-level architecture
  - src/main.py: CLI entry point. Loads environment variables (.env supported), determines headless mode via HEADLESS, and creates TestOrchestrator.
  - src/orchestrator.py: Coordinates the AI planning loop and Selenium execution loop. Applies input rules (quoted literal enforcement for verify/check), handles retries, and renders rich console output.
  - src/ai_agent.py: Provider-agnostic LLM client. Translates a human-readable step plus current page context into a structured JSON command.
  - src/executor.py: Thin Selenium wrapper that performs atomic browser actions with small UX hardening (temporary profile, disabled password manager/notifications, optional stricter suppression).

- End-to-end flow per step
  1) Orchestrator receives the user step string and validates special cases:
     - If the step begins with verify or check, the user must provide the exact text in quotes (single or double). The quoted literal is captured for strict matching later.
  2) AI planning attempts (AI_RETRIES total):
     - Before each AI attempt, Orchestrator pulls a fresh snapshot: page_source and current_url from SeleniumExecutor.
     - It calls AIAgent.translate_step(human_step, page_source, current_url).
     - AIAgent tries to return a JSON command: {"action": ..., ...} or {"error": ...}.
     - If verify/check, Orchestrator overwrites any AI-provided text with the user’s exact quoted literal to guarantee verbatim matching.
  3) Selenium execution attempts (SELENIUM_RETRIES per AI plan):
     - Orchestrator calls Executor methods (navigate, click, type_text, press_key, verify_text). On exceptions, it retries with a short exponential backoff. If all Selenium attempts fail, Orchestrator either asks the AI for a new plan (if any AI attempts remain) or reports failure.

- AIAgent implementation details (src/ai_agent.py)
  - Provider-agnostic configuration via environment variables:
    - Model: LLM_MODEL (or AI_MODEL). Default: gpt-4o.
    - API key: LLM_API_KEY (or OPENAI_API_KEY).
    - Base URL: LLM_BASE_URL (or OPENAI_BASE_URL) for OpenAI-compatible endpoints (OpenRouter/Groq/Together/Fireworks/local Ollama, etc.).
    - Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION. If endpoint is set, the Azure client is preferred and the model name should be your Azure deployment name.
  - Response handling:
    - First tries JSON mode via response_format={"type":"json_object"} (where supported).
    - Falls back to parsing raw text into JSON; includes a small helper to extract the first JSON object from text.
  - Prompting conventions:
    - The system prompt explicitly instructs the model to copy any user-quoted text verbatim for verify/check actions. The Orchestrator enforces this again as a safety belt.
  - No-credentials mode:
    - If no usable client can be created, AIAgent falls back to a lightweight _mock_translate that supports a small subset of commands for demo/testing purposes.
  - Token discipline:
    - To keep prompts smaller, only the first ~5000 characters of page_source are included in the prompt.

- Orchestrator logic (src/orchestrator.py)
  - Input rule: verify/check must include exact text in quotes; otherwise the step is rejected early with a helpful message.
  - Two-layer retry design:
    - AI-level: Up to AI_RETRIES total distinct AI plans.
    - Selenium-level: Up to SELENIUM_RETRIES attempts per AI plan, with short exponential backoff and informative console messages when recovering.
  - Output: Always prints an "AI Thought" line (the JSON command or error), then prints Success/Failure with context. Final failures summarize the last error.
  - Type conversion safeguards: environment integers are clamped to sensible ranges to avoid pathological retry counts.

- SeleniumExecutor implementation (src/executor.py)
  - Browser session:
    - Chrome is started with a fresh temporary user data directory on each run to avoid persistence between tests.
    - Password manager and site notifications are disabled via Chrome prefs. Optional STRICT_NO_PASSWORD_UI enables additional hardening flags and incognito mode to suppress password/autofill prompts.
    - Headless mode is controlled by HEADLESS; when enabled, the modern "--headless=new" is used where supported.
  - Actions:
    - navigate(url): auto-prefixes https:// when no scheme is given.
    - click(selector): waits for element_to_be_clickable and attempts to dismiss transient overlays (ESC) before clicking.
    - type_text(selector, text): waits for presence, clears, then sends keys.
    - press_key(key_name): maps to selenium.webdriver.common.keys.Keys. Raises ValueError on unknown keys (so the orchestrator correctly marks the step as failed and may retry).
    - verify_text(text): performs a strict substring check against the current page_source and raises on mismatch.
  - Cleanup: quit() always tries to close the browser and delete the temporary profile directory.

- Command JSON contract (produced by the AI agent)
  - {"action": "navigate", "url": "..."}
  - {"action": "click", "selector": "..."}
  - {"action": "type", "selector": "...", "value": "..."}
  - {"action": "press_key", "key": "..."}
  - {"action": "verify", "text": "..."}
  - {"error": "..."} when the AI cannot determine a valid action/selector

- Configuration summary (env vars)
  - HEADLESS=true|false – run Chrome headless (useful for CI).
  - STRICT_NO_PASSWORD_UI=true|false – aggressively suppress password/autofill UI and prompts.
  - SELENIUM_RETRIES – per-plan Selenium attempts (default 10; the code clamps environment input to a safe range).
  - AI_RETRIES – total AI planning attempts per step (default 2; minimum 1).
  - LLM_MODEL / AI_MODEL – model or deployment name; see examples in Installation.
  - LLM_API_KEY / OPENAI_API_KEY – API key depending on provider.
  - LLM_BASE_URL / OPENAI_BASE_URL – override endpoint for OpenAI-compatible providers.
  - AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION – Azure-specific settings.

These details are complementary to the Usage and Reliability sections below; together, they describe how inputs are translated into robust browser actions and how failures propagate to provide clear, debuggable outcomes.

## Installation

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create your local environment file from the template:
   ```bash
   cp templates/.env.template .env
   ```
   Then open `.env` and fill in your API key and any options you need. The `.env` file is git-ignored to prevent accidental secret leaks.

   Configure your preferred AI provider in the `.env` file. Quick examples:

   - OpenAI (default):
     ```
     OPENAI_API_KEY=your_openai_key
     # optional overrides
     LLM_MODEL=gpt-5.4-mini
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

### Notes on environment files and secrets
- The repository includes a template at `templates/.env.template`.
- Your local `.env` (at the project root) is ignored by Git via `.gitignore` to avoid committing secrets.
- Never commit real API keys. If you need to share sample configuration, update the template instead.

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
- For exact text values, surround them with quotes in your step inputs. For example:
  - `verify "Google"`
  - `verify 'You logged into a secure area!'`
- Quoted text is treated as an exact literal and will NOT be auto-corrected by the AI (even if it has typos or extra words).
  - Example: `verify "You logged into a secure very area!"` will search for that exact string. If the page shows a different message, the step will fail rather than being "fixed" by the AI.
- `help`: Show usage instructions.
- `exit` or `quit`: Close the tool.

### Browser visibility (headless vs visible)
- By default, TestFlowAI launches a visible Chrome window so you can observe execution.
- To run in headless mode (useful for CI/servers without a display), set the environment variable `HEADLESS=true`.
  - Examples:
    - macOS/Linux: `HEADLESS=true python -m src.main`
    - Windows (PowerShell): `$env:HEADLESS='true'; python -m src.main`
  - You can also put `HEADLESS=true` in your `.env` file.

### Browser profile and prompts
- TestFlowAI starts Chrome with a fresh temporary user data directory on every run. No cookies, cache, or saved passwords are reused.
- The Chrome password manager is disabled and site notifications are blocked to prevent pop-ups and prompts from disrupting automation.

### Reliability and automatic retries
- Each step uses a two-layer retry strategy to improve robustness:
  - Selenium-level retries: the exact set of actions/locators proposed by the AI is attempted up to `SELENIUM_RETRIES` times (default 10).
  - AI-level attempts: if all Selenium attempts fail, the step can be re-planned by the AI up to `AI_RETRIES` times in total (default 2). This number is the total number of AI planning attempts, not “retries plus one”. For example:
    - `AI_RETRIES=1` → up to 1 AI plan (no re-plan).
    - `AI_RETRIES=2` → up to 2 distinct AI plans.
- Configure via environment variables (can be placed in your `.env`):
  - `SELENIUM_RETRIES` (default `10`)
  - `AI_RETRIES` (default `2`, minimum `1`)
- Example:
  ```bash
  SELENIUM_RETRIES=15 AI_RETRIES=2 python -m src.main tests/sample_test.txt
  ```
- A small exponential backoff is applied between Selenium attempts; the page state is refreshed before each AI attempt.

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
