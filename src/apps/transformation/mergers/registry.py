_registry: dict = {}


def register_merger(cls):
    if cls.format in _registry:
        raise TypeError(f"Merger for format '{cls.format}' is already registered")
    _registry[cls.format] = cls
    return cls


def all_mergers(storage) -> dict:
    """Used by MergeServiceFactory to build the injected {format: MergerInterface} map."""
    return {format: cls(storage) for format, cls in _registry.items()}
