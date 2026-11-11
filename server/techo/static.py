from starlette.staticfiles import StaticFiles


class OptionalStaticFiles(StaticFiles):
    """Allow a missing frontend root while retaining Starlette's file handling."""

    async def check_config(self) -> None:
        try:
            await super().check_config()
        except RuntimeError as exc:
            # Starlette wraps a missing root; all other configuration errors still fail.
            if not isinstance(exc.__context__, FileNotFoundError):
                raise
