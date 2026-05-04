"""
AI Agent module for TestFlowAI.
Translates human-readable steps into Selenium commands using OpenAI GPT-4.
"""
import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class AIAgent:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        else:
            self.client = None

    def translate_step(self, human_step, page_source, current_url):
        system_prompt = """
        You are a test automation expert. Given a natural language test step, you must return a JSON object representing the Selenium action to take.
        Use the provided page source to find the best CSS selectors.
        
        Supported actions:
        - {"action": "navigate", "url": "..."}
        - {"action": "click", "selector": "..."}
        - {"action": "type", "selector": "...", "value": "..."}
        - {"action": "press_key", "key": "..."}
        - {"action": "verify", "text": "..."}

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
            # Fallback for demonstration if no API key is provided
            return self._mock_translate(human_step)

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={ "type": "json_object" }
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            return {"error": str(e)}

    def _mock_translate(self, human_step):
        # Very basic mock for testing without API key
        step = human_step.lower()
        if "navigate to" in step or "go to" in step:
            url = step.split("to ")[-1].strip()
            return {"action": "navigate", "url": url}
        elif "click" in step:
            # Try to find a button or link
            return {"action": "click", "selector": "button, a, input[type='submit']"}
        elif "type" in step or "enter" in step:
            value = step.split(":")[-1].strip() if ":" in step else step.split(" ")[-1].strip()
            selector = "input[name='username']" if "username" in step else "input[name='password']" if "password" in step else "input"
            return {"action": "type", "selector": selector, "value": value}
        elif "verify" in step or "check" in step:
            text = step.split("verify ")[-1].strip()
            return {"action": "verify", "text": text}
        
        return {"error": f"Mock agent couldn't parse step: {human_step}. Please provide OPENAI_API_KEY for real AI translation."}
