_registry: dict = {}


def register_converter(cls):
    if cls.format in _registry:
        raise TypeError(f"Converter for format '{cls.format}' is already registered")
    _registry[cls.format] = cls
    return cls


def all_converters(handlers: dict) -> dict:
    """Used by ChunkProcessingServiceFactory to build the injected {format: ConverterInterface} map."""
    return {format: cls(handlers) for format, cls in _registry.items()}
