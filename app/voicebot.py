import openai

def coldcall_lead(messages: list, temperature=0.7, model="gpt-4") -> str:
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        raise RuntimeError(f"AI response failed: {str(e)}")