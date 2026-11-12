from urllib.parse import SplitResult, urlsplit


class OriginNormalization:
    """An origin is scheme, host and port; case and a trailing slash do not change it."""

    @staticmethod
    def normalize_origin(origin: str) -> str | None:
        """The origin in one canonical spelling, or None when it names no site, as the "null" a sandboxed page sends."""
        split_origin: SplitResult = urlsplit(origin.strip().lower())
        if not split_origin.scheme or not split_origin.netloc:
            return None
        return f"{split_origin.scheme}://{split_origin.netloc}"

    @staticmethod
    def read_host(normalized_origin: str) -> str:
        return urlsplit(normalized_origin).netloc
