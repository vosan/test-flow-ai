"""
AI Agent module for TestFlowAI.
Translates human-readable steps into Selenium commands using an LLM.

Provider-agnostic design:
- Supports OpenAI and any OpenAI-compatible API via base_url (e.g., OpenRouter, Groq, Together, Fireworks, local Ollama).
- Optionally supports Azure OpenAI if AZURE_OPENAI_ENDPOINT is configured.

Configuration via environment variables (or constructor args):
- LLM_MODEL (or AI_MODEL) - model/deployment name; default: gpt-4o
- LLM_API_KEY (or OPENAI_API_KEY) - API key (may be optional for local servers like Ollama)
- LLM_BASE_URL (or OPENAI_BASE_URL) - custom base URL for OpenAI-compatible endpoints
- AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION - for Azure OpenAI
"""
import os
import json
import re
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class AIAgent:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # Generic configuration with sensible fallbacks
        self.model = (
            model
            or os.getenv("LLM_MODEL")
            or os.getenv("AI_MODEL")
            or "gpt-4o"
        )

        # Prefer generic LLM_API_KEY, fallback to OPENAI_API_KEY
        env_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

        # Base URL to support OpenAI-compatible providers (OpenRouter, Groq, Together, Fireworks, Ollama, etc.)
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")

        # Azure OpenAI configuration (optional). If provided, we prioritize Azure client.
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.azure_api_key = os.getenv("AZURE_OPENAI_API_KEY") or env_key
        self.azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        self.client = None

        try:
            if self.azure_endpoint:
                # Azure OpenAI uses deployment names as the "model" parameter
                if not self.azure_api_key:
                    raise ValueError("Missing AZURE_OPENAI_API_KEY for Azure OpenAI usage.")
                # Lazy-import AzureOpenAI to avoid hard dependency on specific openai package versions
                try:
                    from openai import AzureOpenAI  # type: ignore
                except Exception as e:
                    raise RuntimeError(
                        "Azure OpenAI client not available in current openai package. "
                        "Please upgrade the 'openai' package to a version that includes AzureOpenAI."
                    ) from e
                self.client = AzureOpenAI(
                    api_key=self.azure_api_key,
                    api_version=self.azure_api_version,
                    azure_endpoint=self.azure_endpoint,
                )
            elif env_key or self.base_url:
                # For local OpenAI-compatible servers (e.g., Ollama), an API key may not be required.
                # The OpenAI client requires some string; 'EMPTY' is commonly accepted by such servers.
                effective_key = env_key or "EMPTY"
                if self.base_url:
                    self.client = OpenAI(api_key=effective_key, base_url=self.base_url)
                else:
                    self.client = OpenAI(api_key=effective_key)
            else:
                # No credentials and no base_url -> use mock
                self.client = None
        except Exception:
            # If anything goes wrong initializing a real client, fall back to mock
            self.client = None

    def translate_step(self, human_step, page_source, current_url):
        system_prompt = """
        You are a test automation expert. Given a natural language test step, you must return a JSON object representing the Selenium action to take.
        Use the provided page source to find the best CSS selectors.
        
        Important input convention:
        - Exact text values in the user's step are always surrounded by quotes (either single ' or double ").
          Example: verify "Login successful" or verify 'Welcome back'.
        - CRITICAL: Any substring provided inside quotes in the human step is an exact literal and MUST be copied verbatim
          to the output JSON without ANY changes. Do NOT fix grammar, spelling, punctuation, whitespace, or wording.
          Do NOT add or remove words.
          For verify/check actions, set the JSON field "text" to exactly the content inside the user's quotes.
          Examples (correct behavior):
            Human: verify "You logged into a secure very area!" -> {"action":"verify", "text":"You logged into a secure very area!"}
            Human: verify 'Login  OK' -> {"action":"verify", "text":"Login  OK"}
          Incorrect (DO NOT do this):
            {"action":"verify", "text":"You logged into a secure area!"}   # removed the word 'very' (WRONG)
            {"action":"verify", "text":"Login OK"}                          # collapsed spaces or changed punctuation (WRONG)
        
        Supported actions:
        - {"action": "navigate", "url": "..."}
        - {"action": "click", "selector": "..."}
        - {"action": "type", "selector": "...", "value": "..."}
        - {"action": "press_key", "key": "..."}
        - {"action": "verify", "text": """ + "..." + """}

        If you cannot determine the action or selector, return:
        {"error": "Reason why it failed"}

        Return ONLY the JSON object.
        """

        user_prompt = f"""
        Current URL: {current_url}
        Human-readable step: {human_step}
        
        Page Source (truncated if too long):
        {page_source[:5000]}
        """

        if not self.client:
            # Fallback for demonstration if no API key / client is provided
            return self._mock_translate(human_step)

        # Try JSON-mode first (OpenAI and some compatible providers). If it fails,
        # retry without JSON enforcement and attempt to extract a JSON object.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Attempt 1: JSON response_format
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception:
            pass

        # Attempt 2: Without response_format, parse JSON from text
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            content = response.choices[0].message.content or ""
            # Try direct JSON first
            try:
                return json.loads(content)
            except Exception:
                # Fallback: extract the first JSON object substring
                obj = self._extract_json_object(content)
                if obj is not None:
                    return obj
                return {"error": f"Model returned non-JSON content: {content[:200]}..."}
        except Exception as e:
            return {"error": str(e)}

    def _extract_json_object(self, text: str):
        # Find the first {...} block that looks like a JSON object
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            # Remove trailing code fences/backticks if any
            candidate = candidate.strip().strip("`")
            try:
                return json.loads(candidate)
            except Exception:
                # Try a more lenient approach: remove trailing commas, etc. (very limited)
                cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    return json.loads(cleaned)
                except Exception:
                    return None
        return None

    def _mock_translate(self, human_step):
        # Very basic mock for testing without API client
        step = human_step.lower()
        if "navigate to" in step or "go to" in step:
            url = step.split("to ")[-1].strip()
            return {"action": "navigate", "url": url}
        elif "click" in step:
            # Try to find a button or link
            return {"action": "click", "selector": "button, a, input[type='submit']"}
        elif "type" in step or "enter" in step:
            value = step.split(":")[-1].strip() if ":" in step else step.split(" ")[-1].strip()
            selector = (
                "input[name='username']" if "username" in step else
                "input[name='password']" if "password" in step else
                "input"
            )
            return {"action": "type", "selector": selector, "value": value}
        elif "verify" in step or "check" in step:
            # Expect quoted exact text, either single or double quotes
            m = re.search(r"(?:verify|check)\s+(['\"])(.*?)\1\s*$", human_step, flags=re.IGNORECASE)
            if not m:
                return {
                    "error": (
                        "Exact text must be surrounded with quotes. Example: verify \"Google\" or verify 'Google'"
                    )
                }
            quoted_text = m.group(2)
            return {"action": "verify", "text": quoted_text}

        return {
            "error": (
                f"Mock agent couldn't parse step: {human_step}. "
                f"Configure a real LLM via OPENAI_API_KEY/LLM_API_KEY (and optional LLM_BASE_URL) for AI translation."
            )
        }
