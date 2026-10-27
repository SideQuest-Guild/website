"""``sidequest-api``: serve the API with uvicorn."""


def main() -> None:
    """Run the API on ``API_HOST``:``API_PORT``."""
    import uvicorn

    from sidequest_common.settings import APISettings

    settings = APISettings()
    uvicorn.run("sidequest_api.app:create_app", factory=True, host=settings.HOST, port=settings.PORT)


if __name__ == "__main__":
    main()
