"""
Run the API first (e.g. `uvicorn main:app`), then: python examples/quickstart.py
"""

from terngi import TerngiClient

with TerngiClient(base_url="http://localhost:8000") as client:  # add api_key="..." if required
    # 1. Chat, continuing the same conversation
    print("--- Chat ---")
    first = client.chat("Bawo ni! Orúkọ mi ni Adé.")
    print(first.reply)
    second = client.chat("Kí ni orúkọ mi?", conversation_id=first.conversation_id)
    print(second.reply)

    # 2. Streaming chat: print the reply as it is generated
    print("\n--- Streaming chat ---")
    for event in client.chat_stream("Explain photosynthesis in two sentences."):
        if event.event == "token":
            print(event.data["text"], end="", flush=True)
        elif event.event == "done":
            print()

    # 3. Detect a language
    print("\n--- Detect ---")
    detected = client.detect("Ẹ káàrọ̀, báwo ni?")
    print(f"{detected.language_name} ({detected.language}), score {detected.score}")

    # 4. Translate
    print("\n--- Translate ---")
    print(client.translate("Good morning", to_language="yo").translated_text)
    print(client.translate_batch(["Thank you", "Good night"], to_language="ha").translations)
