import apps.transformation.converters  # noqa: F401 — triggers @register_converter side effects
import apps.transformation.handlers  # noqa: F401 — triggers @register_handler side effects
import apps.transformation.mergers  # noqa: F401 — triggers @register_merger side effects
from apps.transformation.converters.registry import all_converters
from apps.transformation.factories.cache_factory import CacheAdapterFactory
from apps.transformation.factories.storage_factory import StorageFactory
from apps.transformation.handlers.registry import all_handlers
from apps.transformation.mergers.registry import all_mergers
from apps.transformation.repositories.job_repository import JobRepository
from apps.transformation.repositories.supplier_repository import \
    SupplierRepository
from apps.transformation.repositories.template_repository import \
    TemplateRepository
from apps.transformation.services.chunk_processing_service import \
    ChunkProcessingService
from apps.transformation.services.job_lifecycle_service import \
    JobLifecycleService
from apps.transformation.services.mapping_service import MappingService
from apps.transformation.services.merge_service import MergeService
from apps.transformation.services.source_field_service import \
    SourceFieldService
from apps.transformation.services.template_lifecycle_service import \
    TemplateLifecycleService
from apps.transformation.services.template_service import TemplateService
from apps.transformation.services.transformation_service import \
    TransformationService


class TransformationServiceFactory:
    """Wires TransformationService with all its dependencies."""

    @staticmethod
    def create() -> TransformationService:
        return TransformationService(
            supplier_repository=SupplierRepository(),
            template_repository=TemplateRepository(),
            job_repository=JobRepository(),
            cache=CacheAdapterFactory.create(),
            storage=StorageFactory.create(),
        )


class TemplateLifecycleServiceFactory:
    """Wires TemplateLifecycleService with its repositories."""

    @staticmethod
    def create() -> TemplateLifecycleService:
        return TemplateLifecycleService(
            repository=TemplateRepository(),
            supplier_repository=SupplierRepository(),
        )


class TemplateServiceFactory:
    """Wires TemplateService with its repositories."""

    @staticmethod
    def create() -> TemplateService:
        return TemplateService(
            template_repository=TemplateRepository(),
            supplier_repository=SupplierRepository(),
        )


class SourceFieldServiceFactory:
    """Wires SourceFieldService with its repositories."""

    @staticmethod
    def create() -> SourceFieldService:
        return SourceFieldService(
            repository=TemplateRepository(),
            supplier_repository=SupplierRepository(),
        )


class MappingServiceFactory:
    """Wires MappingService with its repositories."""

    @staticmethod
    def create() -> MappingService:
        return MappingService(
            repository=TemplateRepository(),
            supplier_repository=SupplierRepository(),
        )


class JobLifecycleServiceFactory:
    """Wires JobLifecycleService with its repository and cache."""

    @staticmethod
    def create() -> JobLifecycleService:
        return JobLifecycleService(
            job_repository=JobRepository(),
            cache=CacheAdapterFactory.create(),
        )


class ChunkProcessingServiceFactory:
    """Wires ChunkProcessingService with its repositories, cache, converters, and storage."""

    @staticmethod
    def create() -> ChunkProcessingService:
        return ChunkProcessingService(
            template_repository=TemplateRepository(),
            job_repository=JobRepository(),
            cache=CacheAdapterFactory.create(),
            converters=all_converters(all_handlers()),
            storage=StorageFactory.create(),
            lifecycle=JobLifecycleServiceFactory.create(),
        )


class MergeServiceFactory:
    """Wires MergeService with its repositories, mergers, storage, and lifecycle."""

    @staticmethod
    def create() -> MergeService:
        storage = StorageFactory.create()
        return MergeService(
            template_repository=TemplateRepository(),
            job_repository=JobRepository(),
            mergers=all_mergers(storage),
            storage=storage,
            lifecycle=JobLifecycleServiceFactory.create(),
        )
