"""Errors a storage adapter raises that the application must react to."""


class BlobExistsError(RuntimeError):
    """The blob exists with different content and replacing was not authorised."""
