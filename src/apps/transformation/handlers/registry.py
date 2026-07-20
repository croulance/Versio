_registry: dict = {}


def register_handler(cls):
    if cls.name in _registry:
        raise TypeError(f"Handler '{cls.name}' is already registered")
    _registry[cls.name] = cls
    return cls


def all_handlers() -> dict:
    """Used by ChunkProcessingServiceFactory (via all_converters()) to build the injected {name: FieldHandler} map."""
    return {name: cls() for name, cls in _registry.items()}


def list_handlers() -> list[str]:
    return sorted(_registry.keys())
