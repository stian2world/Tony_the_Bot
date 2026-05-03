"""Groq LLM wrapper for Tony, using a personality prompt sourced from Figurate."""

from groq import Groq


class TonyGroq:
    def __init__(self, api_key: str, model: str = "llama3-8b-8192", system_prompt: str = ""):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt or (
            "You are Tony, a helpful classroom assistant. "
            "Answer clearly and concisely, always staying in character."
        )

    def ask(self, question: str, prior_answer: str = "") -> str:
        messages = [{"role": "system", "content": self.system_prompt}]
        if prior_answer:
            messages.append({
                "role": "system",
                "content": (
                    f"A similar question was previously answered: {prior_answer}\n"
                    "Use this as context but tailor your reply to the current question."
                ),
            })
        messages.append({"role": "user", "content": question})
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()

    def chat(self, history: list[dict]) -> str:
        """Multi-turn chat; history is a list of {role, content} dicts."""
        messages = [{"role": "system", "content": self.system_prompt}] + history
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
