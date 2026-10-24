"""Static accessibility checks for the built-in chat page (#41)."""

from html.parser import HTMLParser
from pathlib import Path

CHAT_HTML = Path(__file__).resolve().parent.parent / "static" / "chat.html"

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


class _Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = attrs
        self.text: list[str] = []


class _Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes: list[_Node] = []
        self._open: list[_Node] = []

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.nodes.append(node)
        if tag not in VOID_TAGS:
            self._open.append(node)

    def handle_startendtag(self, tag, attrs):
        self.nodes.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    def handle_data(self, data):
        for node in self._open:
            node.text.append(data)

    def by_id(self, element_id):
        return next(node for node in self.nodes if node.attrs.get("id") == element_id)

    def text_of(self, node):
        return " ".join("".join(node.text).split())


def parse_page():
    page = _Page()
    page.feed(CHAT_HTML.read_text(encoding="utf-8"))
    return page


def test_messages_are_a_polite_live_log():
    log = parse_page().by_id("messages")

    assert log.attrs.get("role") == "log"
    assert log.attrs.get("aria-live") == "polite"
    assert "additions" in log.attrs.get("aria-relevant", "")


def test_transcript_can_be_scrolled_from_the_keyboard():
    page = parse_page()
    scroller = page.by_id("scroll")

    assert scroller.tag == "main"
    assert scroller.attrs.get("tabindex") == "0"
    assert scroller.attrs.get("aria-label")


def test_composer_and_settings_fields_have_labels():
    page = parse_page()
    message = page.by_id("input")
    api_key = page.by_id("api-key")
    reply_language = page.by_id("reply-language")

    assert message.attrs.get("aria-label") == "Message"
    assert message.attrs.get("aria-describedby") == "input-hint"
    assert page.by_id("input-hint")
    assert api_key.attrs.get("aria-label") == "API key"
    assert api_key.attrs.get("type") == "password"
    assert reply_language.attrs.get("aria-label") == "Reply language"


def test_buttons_and_summary_have_accessible_text():
    page = parse_page()

    for node in page.nodes:
        if node.tag in {"button", "summary"}:
            assert page.text_of(node), f"{node.tag} has no accessible text: {node.attrs}"


def test_interactive_elements_have_a_visible_focus_style():
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert ":focus-visible" in html
    assert "outline: 3px solid var(--accent)" in html
    assert "outline: none" not in html


def test_final_streamed_reply_is_appended_as_one_complete_message():
    html = CHAT_HTML.read_text(encoding="utf-8")

    # The live log announces additions. The final reply must be a new message,
    # not a text update inside the streaming bubble.
    assert 'addMessage("bot", data.reply, meta)' in html
