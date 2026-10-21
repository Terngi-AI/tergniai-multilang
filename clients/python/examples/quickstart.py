from terngi import TerngiClient

with TerngiClient(api_key="demo-key", base_url="http://localhost:8000") as client:
    # 1. Chat
    print("--- Testing Chat ---")
    chat_out = client.chat("Bawo ni o se wa?")
    print(chat_out.response)

    # 2. Detect Language
    print("\n--- Testing Detect ---")
    detected = client.detect("E kaaro, bawo ni?")
    print(f"Language: {detected.language} (Confidence: {detected.confidence})")

    # 3. Translate
    print("\n--- Testing Translation ---")
    translation = client.translate("Good morning", target_lang="yo")
    print(f"Translation: {translation.translated_text}")
