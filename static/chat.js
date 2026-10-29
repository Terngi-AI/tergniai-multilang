(() => {
  const TRANSLATIONS = {
    en: {
      uiLangLabel: "Interface:",
      replyInLabel: "Reply in",
      sameLanguageOption: "Same language as me",
      newChat: "New chat",
      settings: "Settings",
      apiKeyLabel: "API key",
      apiKeyPlaceholder: "Only if the server requires one",
      rememberKey: "Remember on this device",
      forgetKey: "Forget key",
      welcomeSub: "Chat with Terngi AI about anything, in your own language.",
      inputPlaceholder: "Message Terngi AI…",
      inputAriaLabel: "Message",
      send: "Send",
      hint: "Enter to send · Shift+Enter for a new line. Conversations are kept on the server for 24 hours.",
      typing: "Terngi AI is thinking…",
      usingTool: "Terngi AI is using",
      newChatGreeting: "New conversation started. What would you like to talk about?",
      expiredError: "That conversation expired. Your next message starts a new one.",
      genericError: "Something went wrong.",
      networkError: "Couldn't reach the server. Check your connection and try again.",
      usedTools: "used"
    },
    yo: {
      uiLangLabel: "Èdè UI:",
      replyInLabel: "Dáhùn ní",
      sameLanguageOption: "Èdè kan náà pẹ̀lú mi",
      newChat: "Ọ̀rọ̀ tuntun",
      settings: "Ètò",
      apiKeyLabel: "Kọ́kọ́rọ́ API",
      apiKeyPlaceholder: "Kìkì tí olupin bá béèrè fún un",
      welcomeSub: "Bá Terngi AI sọ̀rọ̀ nípa ohunkóhun, ní èdè rẹ.",
      inputPlaceholder: "Firanṣẹ́ sí Terngi AI…",
      inputAriaLabel: "Ifiranṣẹ́",
      send: "Firanṣẹ́",
      hint: "Enter láti firanṣẹ́ · Shift+Enter fún ìlà tuntun. Ìjíròrò yóò wà lórí olupin fún wákàtí 24.",
      typing: "Terngi AI ń rò ó…",
      usingTool: "Terngi AI ń lo",
      newChatGreeting: "Ìjíròrò tuntun ti bẹ̀rẹ̀. Kí ni o fẹ́ ká sọ̀rọ̀ nípa rẹ̀?",
      expiredError: "Ìjíròrò yẹn ti parí. Ìfiranṣẹ́ rẹ tí ó kàn yóò bẹ̀rẹ̀ tuntun.",
      genericError: "Nǹkan kan tọsẹ.",
      networkError: "Kò lè dé ọ̀dọ̀ olupin. Yẹ asopọ rẹ wò kí o tún gbìyànjú.",
      usedTools: "lo"
    },
    ha: {
      uiLangLabel: "Harshen shafi:",
      replyInLabel: "Amsa a",
      sameLanguageOption: "Harshe ɗaya da ni",
      newChat: "Sabuwar hira",
      settings: "Saituna",
      apiKeyLabel: "Mabuɗin API",
      apiKeyPlaceholder: "Idan har uwar garken na buƙata kawai",
      welcomeSub: "Yi hira da Terngi AI game da komai, cikin yarenka.",
      inputPlaceholder: "Aika saƙo zuwa Terngi AI…",
      inputAriaLabel: "Saƙo",
      send: "Aika",
      hint: "Danna Enter don aikawa · Shift+Enter don sabon layi. Ana adana hirarraki na tsawon awanni 24.",
      typing: "Terngi AI yana tunani…",
      usingTool: "Terngi AI yana amfani da",
      newChatGreeting: "An fara sabuwar hira. Me kuke so mu tattauna akai?",
      expiredError: "Waccan hirar ta ƙare. Saƙonku na gaba zai fara sabuwa.",
      genericError: "Wani abu ya sami matsala.",
      networkError: "An kasa isa ga uwar garken. Duba hanyar sadarwarka sannan ka sake gwadawa.",
      usedTools: "anyi amfani da"
    },
    ig: {
      uiLangLabel: "Asụsụ Ihuenyo:",
      replyInLabel: "Zaa na",
      sameLanguageOption: "Otu asụsụ ahụ m ji dee",
      newChat: "Mkparịta ụka ọhụrụ",
      settings: "Ntọala",
      apiKeyLabel: "Igodo API",
      apiKeyPlaceholder: "Naanị ma sava chọrọ ya",
      welcomeSub: "Kparịta ụka na Terngi AI gbasara ihe ọ bụla, n'asụsụ gị.",
      inputPlaceholder: "Ziga ozi na Terngi AI…",
      inputAriaLabel: "Ozi",
      send: "Ziga",
      hint: "Enter iji ziga · Shift+Enter maka ahịrị ọhụrụ. A na-edebe mkparịta ụka na sava ruo awa 24.",
      typing: "Terngi AI na-eche echiche…",
      usingTool: "Terngi AI na-eji",
      newChatGreeting: "Amalitere mkparịta ụka ọhụrụ. Kedu ihe ị ga-achọ ka anyị kpaa maka ya?",
      expiredError: "Mkparịta ụka ahụ agwụla. Ozi ọzọ ị ga-eziga ga-amalite nke ọhụrụ.",
      genericError: "Ihe mebiri.",
      networkError: "Enweghị ike iru sava ahụ. Lelee njikọ gị ma nwaa ọzọ.",
      usedTools: "jiri"
    },
    pcm: {
      uiLangLabel: "Language:",
      replyInLabel: "Reply with",
      sameLanguageOption: "The same language wey I use",
      newChat: "New chat",
      settings: "Settings",
      apiKeyLabel: "API key",
      apiKeyPlaceholder: "Only if server need am",
      welcomeSub: "Follow Terngi AI yarn about anything, for your own language.",
      inputPlaceholder: "Message Terngi AI…",
      inputAriaLabel: "Message",
      send: "Send",
      hint: "Enter to send · Shift+Enter for new line. Server dey keep chat for 24 hours.",
      typing: "Terngi AI dey reason…",
      usingTool: "Terngi AI dey use",
      newChatGreeting: "New gist don start. Wetin you wan talk about?",
      expiredError: "Dat gist don expire. Your next message go start new one.",
      genericError: "Wahala dey.",
      networkError: "Network no reach server. Check your connection try again.",
      usedTools: "use"
    },
    sw: {
      uiLangLabel: "Lugha:",
      replyInLabel: "Jibu kwa",
      sameLanguageOption: "Lugha sawa na yangu",
      newChat: "Gumzo jipya",
      settings: "Mipangilio",
      apiKeyLabel: "Ufunguo wa API",
      apiKeyPlaceholder: "Ikiwa tu seva inaihitaji",
      welcomeSub: "Zungumza na Terngi AI kuhusu chochote, katika lugha yako.",
      inputPlaceholder: "Tuma ujumbe kwa Terngi AI…",
      inputAriaLabel: "Ujumbe",
      send: "Tuma",
      hint: "Enter kutuma · Shift+Enter kwa mstari mpya. Mazungumzo huwekwa kwenye seva kwa saa 24.",
      typing: "Terngi AI anafikiria…",
      usingTool: "Terngi AI anatumia",
      newChatGreeting: "Mazungumzo mapya yameanza. Ungependa kuzungumza kuhusu nini?",
      expiredError: "Mazungumzo hayo yamekwisha muda wake. Ujumbe wako unaofuata utaanza mapya.",
      genericError: "Hitilafu imetokea.",
      networkError: "Haikuweza kuunganishwa na seva. Angalia mtandao wako kisha ujaribu tena.",
      usedTools: "imetumia"
    }
  };

  const SUPPORTED_LANGS = Object.keys(TRANSLATIONS);

  const messages = document.getElementById("messages");
  const scroller = document.getElementById("scroll");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const replySelect = document.getElementById("reply-language");
  const uiLanguageSelect = document.getElementById("ui-language");
  const apiKeyInput = document.getElementById("api-key");
  const rememberKey = document.getElementById("remember-key");
  const forgetKey = document.getElementById("forget-key");
  let conversationId = null;
  let busy = false;

  // localStorage access can throw (private browsing, disabled storage): fail soft
  const safeStorage = (storage) => ({
    get(key) { try { return storage.getItem(key); } catch { return null; } },
    set(key, value) { try { storage.setItem(key, value); } catch {} },
    remove(key) { try { storage.removeItem(key); } catch {} },
  });
  const store = safeStorage(localStorage);
  const sessionStore = safeStorage(sessionStorage);

  function resolveLanguage() {
    const saved = store.get("terngi.uiLanguage");
    if (saved && SUPPORTED_LANGS.includes(saved)) return saved;
    const nav = (navigator.language || "").split("-")[0].toLowerCase();
    return SUPPORTED_LANGS.includes(nav) ? nav : "en";
  }

  let currentLang = resolveLanguage();

  function applyLanguage(lang) {
    if (!TRANSLATIONS[lang]) lang = "en";
    currentLang = lang;
    store.set("terngi.uiLanguage", lang);
    document.documentElement.lang = lang;
    uiLanguageSelect.value = lang;

    const dict = TRANSLATIONS[lang];

    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      if (dict[key]) el.textContent = dict[key];
    });

    document.querySelectorAll("[data-i18n-attr]").forEach(el => {
      const mappings = el.getAttribute("data-i18n-attr").split(",");
      mappings.forEach(mapping => {
        const [attr, key] = mapping.split(":");
        if (dict[key]) el.setAttribute(attr, dict[key]);
      });
    });
  }

  uiLanguageSelect.value = currentLang;
  applyLanguage(currentLang);
  uiLanguageSelect.addEventListener("change", (e) => applyLanguage(e.target.value));

  // --- API key storage ------------------------------------------------------
  //
  // The key lives in sessionStorage by default, so closing the browser forgets it
  // (shared computers). localStorage is only used when the user explicitly checks
  // "Remember on this device".
  const localKey = {
    get() { return store.get("terngi.apiKey"); },
    set(value) { store.set("terngi.apiKey", value); },
    remove() { store.remove("terngi.apiKey"); },
  };

  function saveKey() {
    const key = apiKeyInput.value.trim();
    if (key) {
      sessionStore.set("terngi.apiKey", key);
      if (rememberKey.checked) localKey.set(key);
    } else {
      sessionStore.remove("terngi.apiKey");
      localKey.remove();
    }
    if (rememberKey.checked) store.set("terngi.rememberKey", "1");
    else store.remove("terngi.rememberKey");
  }

  // Upgrade path: older versions stored the key in localStorage without asking. Move
  // it into the session so it stops surviving browser restarts, without making the
  // user type it again.
  if (store.get("terngi.rememberKey") === "1") {
    rememberKey.checked = true;
    apiKeyInput.value = localKey.get() || "";
  } else {
    const legacyKey = localKey.get();
    if (legacyKey) {
      localKey.remove();
      sessionStore.set("terngi.apiKey", legacyKey);
    }
    apiKeyInput.value = sessionStore.get("terngi.apiKey") || "";
  }

  apiKeyInput.addEventListener("change", saveKey);
  rememberKey.addEventListener("change", saveKey);
  forgetKey.addEventListener("click", () => {
    rememberKey.checked = false;
    apiKeyInput.value = "";
    saveKey();
    apiKeyInput.focus();
  });

  const suggestions = [
    "Ẹ káàrọ̀! Báwo ni o ṣe lè ràn mí lọ́wọ́ lónìí?",
    "Wetin I fit cook for dinner with rice and beans?",
    "Explain how compound interest works, simply.",
    "Habari! Nisaidie kuandika barua ya kazi.",
  ];
  const suggestionBox = document.getElementById("suggestions");
  for (const text of suggestions) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = text;
    b.addEventListener("click", () => { input.value = text; submit(); });
    suggestionBox.appendChild(b);
  }

  fetch("/v1/languages").then(r => r.json()).then(({ languages }) => {
    for (const [code, name] of Object.entries(languages)) {
      const option = document.createElement("option");
      option.value = code;
      option.textContent = name;
      replySelect.appendChild(option);
    }
    replySelect.value = store.get("terngi.replyLanguage") || "";
  }).catch(() => {});
  replySelect.addEventListener("change", () => store.set("terngi.replyLanguage", replySelect.value));

  function render(el, text) {
    el.replaceChildren();
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    for (const part of parts) {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        const b = document.createElement("strong"); b.textContent = part.slice(2, -2); el.appendChild(b);
      } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
        const c = document.createElement("code"); c.textContent = part.slice(1, -1); el.appendChild(c);
      } else if (part) {
        el.appendChild(document.createTextNode(part));
      }
    }
  }

  function addMessage(role, text, meta) {
    document.getElementById("welcome")?.remove();
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    render(el, text);
    if (meta) {
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      el.appendChild(m);
    }
    messages.appendChild(el);
    scroller.scrollTop = scroller.scrollHeight;
    return el;
  }

  // Optional, opt-in feedback. Nothing is sent until the user ticks the consent box.
  function addFeedback(el, exchange) {
    if (!exchange.from_language || !exchange.to_language) return;

    const box = document.createElement("div");
    box.className = "feedback";
    const label = document.createElement("span");
    label.textContent = "Rate this reply:";
    const good = document.createElement("button");
    good.type = "button";
    good.textContent = "👍";
    good.setAttribute("aria-label", "Good reply");
    const bad = document.createElement("button");
    bad.type = "button";
    bad.textContent = "👎";
    bad.setAttribute("aria-label", "Bad reply");
    const status = document.createElement("span");
    status.className = "feedback-status";
    status.setAttribute("role", "status");
    box.append(label, good, bad, status);
    el.appendChild(box);

    let panel = null;

    function choose(rating) {
      if (panel) { panel.remove(); panel = null; }
      status.textContent = "";

      panel = document.createElement("div");
      panel.className = "feedback-panel";

      const notice = document.createElement("p");
      notice.className = "notice";
      notice.textContent = "Feedback is optional. With your consent it is stored and may be " +
        "published as part of Terngi's open evaluation set. Do not include personal information.";

      const correction = document.createElement("textarea");
      correction.rows = 2;
      correction.placeholder = "Suggest a better reply (optional)";
      correction.setAttribute("aria-label", "Suggest a better reply");

      const consentLabel = document.createElement("label");
      consentLabel.className = "consent";
      const consent = document.createElement("input");
      consent.type = "checkbox";
      const consentText = document.createElement("span");
      consentText.textContent = "I agree that this feedback may be stored and published in the " +
        "open evaluation set.";
      consentLabel.append(consent, consentText);

      const actions = document.createElement("div");
      actions.className = "feedback-actions";
      const submit = document.createElement("button");
      submit.type = "button";
      submit.className = "primary";
      submit.textContent = "Send feedback";
      submit.disabled = true;
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Cancel";
      actions.append(submit, cancel);

      consent.addEventListener("change", () => { submit.disabled = !consent.checked; });
      cancel.addEventListener("click", () => { panel?.remove(); panel = null; });

      submit.addEventListener("click", async () => {
        if (!consent.checked) return;
        submit.disabled = true;
        submit.textContent = "Sending…";
        const body = {
          source_text: exchange.source_text,
          translated_text: exchange.translated_text,
          from_language: exchange.from_language,
          to_language: exchange.to_language,
          provider: "chat",
          rating,
          consent: true,
        };
        const better = correction.value.trim();
        if (better) body.correction = better;
        try {
          const res = await fetch("/v1/feedback", {
            method: "POST", headers: headers(), body: JSON.stringify(body),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.message || `Could not send feedback (${res.status}).`);
          }
          panel?.remove(); panel = null;
          good.disabled = true; bad.disabled = true;
          status.textContent = "Thanks for the feedback.";
        } catch (err) {
          status.textContent = err.message || "Could not send feedback.";
          submit.disabled = false;
          submit.textContent = "Try again";
        }
      });

      panel.append(notice, correction, consentLabel, actions);
      box.appendChild(panel);
      correction.focus();
    }

    good.addEventListener("click", () => choose("good"));
    bad.addEventListener("click", () => choose("bad"));
  }

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 180) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(); }
  });
  document.getElementById("composer").addEventListener("submit", e => { e.preventDefault(); submit(); });

  document.getElementById("new-chat").addEventListener("click", () => {
    if (conversationId) {
      fetch(`/v1/chat/${conversationId}`, { method: "DELETE", headers: headers() }).catch(() => {});
    }
    conversationId = null;
    messages.replaceChildren();
    addMessage("bot", TRANSLATIONS[currentLang].newChatGreeting);
    input.focus();
  });

  function headers() {
    const h = { "Content-Type": "application/json" };
    const key = apiKeyInput.value.trim();
    if (key) h["X-API-Key"] = key;
    return h;
  }

  async function readEvents(stream, onEvent) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "message";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith("data: ")) {
          const payload = line.slice(6).trim();
          if (payload) {
            try {
              onEvent(currentEvent, JSON.parse(payload));
            } catch {}
          }
          currentEvent = "message";
        }
      }
    }
  }

  async function submit() {
    const text = input.value.trim();
    if (!text || busy) return;
    busy = true; send.disabled = true;
    input.value = ""; autosize();
    addMessage("user", text);

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = TRANSLATIONS[currentLang].typing;
    messages.appendChild(typing);
    scroller.scrollTop = scroller.scrollHeight;

    const body = { message: text };
    if (conversationId) body.conversation_id = conversationId;
    if (replySelect.value) body.reply_language = replySelect.value;

    let bubble = null;
    let streamed = "";
    const usedTools = new Set();
    const ensureBubble = () => {
      if (!bubble) {
        bubble = addMessage("bot", "");
        messages.appendChild(typing);
      }
      return bubble;
    };

    try {
      const res = await fetch("/v1/chat/stream", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(body),
      });

      if (res.status === 404 && conversationId) {
        typing.remove();
        conversationId = null;
        addMessage("error", TRANSLATIONS[currentLang].expiredError);
        return;
      }

      if (!res.ok) {
        typing.remove();
        const data = await res.json().catch(() => ({}));
        addMessage("error", data.message || `${TRANSLATIONS[currentLang].genericError} (${res.status}).`);
        return;
      }

      await readEvents(res.body, (event, data) => {
        if (event === "start") {
          conversationId = data.conversation_id;
        } else if (event === "token") {
          streamed += data.text;
          ensureBubble().textContent = streamed;
          scroller.scrollTop = scroller.scrollHeight;
        } else if (event === "discard") {
          streamed = "";
          if (bubble) bubble.textContent = "";
        } else if (event === "tool") {
          usedTools.add(data.tool);
          typing.textContent = `${TRANSLATIONS[currentLang].usingTool} ${data.tool.replace(/_/g, " ")}…`;
        } else if (event === "done") {
          conversationId = data.conversation_id;
          if (bubble) { bubble.remove(); bubble = null; }
          typing.remove();
          const meta = usedTools.size ? `${TRANSLATIONS[currentLang].usedTools}: ${[...usedTools].join(", ")}` : null;
          const replyBubble = addMessage("bot", data.reply, meta);
          addFeedback(replyBubble, {
            source_text: text,
            translated_text: data.reply,
            from_language: data.language,
            to_language: data.reply_language,
          });
        } else if (event === "error") {
          bubble?.remove();
          bubble = null;
          typing.remove();
          addMessage("error", data.message || TRANSLATIONS[currentLang].genericError);
        }
      });
    } catch (err) {
      if (typing.parentNode) typing.remove();
      addMessage("error", TRANSLATIONS[currentLang].networkError);
    } finally {
      busy = false; send.disabled = false; input.focus();
    }
  }

  input.focus();
})();
