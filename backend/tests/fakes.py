"""Shared offline test doubles."""


class FakeResponse:
    def __init__(self, status_code=200, content_type="text/html", final_url=None, text=""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.url = final_url or "https://example.com/final"
        self.text = text


class FakeAsyncClient:
    """Fake ``httpx.AsyncClient`` for exercising fetch paths offline."""

    def __init__(self, **kwargs):
        self.responses = {}
        self.errors = {}

    def route(self, url, response=None, error=None):
        self.responses[url] = response
        if error is not None:
            self.errors[url] = error

    async def get(self, url):
        if url in self.errors:
            raise self.errors[url]
        return self.responses.get(url, FakeResponse())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False