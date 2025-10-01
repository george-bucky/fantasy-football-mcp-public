"""
Configuration module for the hybrid fantasy football optimization system.

This module provides configuration management for the various components
of the hybrid optimization system, allowing for easy customization and
environment-specific settings.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from ..models.lineup import OptimizationStrategy


class Environment(str, Enum):
    """Deployment environments."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMModel(str, Enum):
    """Available LLM models."""

    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4_TURBO = "gpt-4-turbo"
    GPT_3_5_TURBO = "gpt-3.5-turbo"


@dataclass
class LLMConfig:
    """Configuration for LLM enhancement."""

    api_key: str
    model: LLMModel = LLMModel.GPT_4O_MINI
    temperature: float = 0.1
    max_tokens: int = 2000
    timeout_seconds: int = 30
    retry_attempts: int = 3
    enable_caching: bool = True
    cache_ttl_seconds: int = 3600


@dataclass
class OptimizationConfig:
    """Configuration for mathematical optimization."""

    max_workers: int = 4
    use_genetic_algorithm: bool = True
    genetic_population_size: int = 1000
    genetic_generations: int = 200
    genetic_mutation_rate: float = 0.1
    genetic_crossover_rate: float = 0.8
    enable_parallel_processing: bool = True
    max_alternatives: int = 5


@dataclass
class EnhancementConfig:
    """Configuration for LLM enhancement features."""

    enable_explanations: bool = True
    enable_alternatives: bool = True
    enable_edge_case_handling: bool = True
    enable_strategy_adaptation: bool = True
    enable_user_interactions: bool = True
    enable_context_analysis: bool = True
    max_explanation_length: int = 1000
    max_alternatives_count: int = 3


@dataclass
class PerformanceConfig:
    """Configuration for performance optimization."""

    enable_caching: bool = True
    cache_size_mb: int = 100
    enable_compression: bool = True
    enable_metrics: bool = True
    metrics_retention_days: int = 30
    enable_profiling: bool = False


@dataclass
class LoggingConfig:
    """Configuration for logging."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    enable_file_logging: bool = False
    log_file_path: str = "fantasy_optimizer.log"
    max_file_size_mb: int = 10
    backup_count: int = 5


@dataclass
class HybridOptimizerConfig:
    """Main configuration for the hybrid optimizer system."""

    # Environment
    environment: Environment = Environment.DEVELOPMENT

    # Component configurations
    llm: LLMConfig = field(default_factory=LLMConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    enhancement: EnhancementConfig = field(default_factory=EnhancementConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Feature flags
    enable_llm_enhancement: bool = True
    enable_hybrid_mode: bool = True
    enable_fallback_mode: bool = True

    # Default strategies
    default_strategy: OptimizationStrategy = OptimizationStrategy.BALANCED
    fallback_strategy: OptimizationStrategy = OptimizationStrategy.SAFE

    # Rate limiting
    max_optimizations_per_minute: int = 10
    max_interactions_per_minute: int = 30

    # Data validation
    strict_validation: bool = True
    validate_player_data: bool = True
    validate_lineup_constraints: bool = True

    @classmethod
    def from_environment(cls) -> "HybridOptimizerConfig":
        """Create configuration from environment variables."""
        config = cls()

        # LLM Configuration
        config.llm.api_key = os.getenv("OPENAI_API_KEY", "")
        config.llm.model = LLMModel(os.getenv("LLM_MODEL", LLMModel.GPT_4O_MINI.value))
        config.llm.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        config.llm.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2000"))
        config.llm.timeout_seconds = int(os.getenv("LLM_TIMEOUT", "30"))

        # Optimization Configuration
        config.optimization.max_workers = int(os.getenv("OPTIMIZATION_MAX_WORKERS", "4"))
        config.optimization.use_genetic_algorithm = (
            os.getenv("USE_GENETIC_ALGORITHM", "true").lower() == "true"
        )
        config.optimization.genetic_population_size = int(
            os.getenv("GENETIC_POPULATION_SIZE", "1000")
        )
        config.optimization.genetic_generations = int(os.getenv("GENETIC_GENERATIONS", "200"))

        # Enhancement Configuration
        config.enhancement.enable_explanations = (
            os.getenv("ENABLE_EXPLANATIONS", "true").lower() == "true"
        )
        config.enhancement.enable_alternatives = (
            os.getenv("ENABLE_ALTERNATIVES", "true").lower() == "true"
        )
        config.enhancement.enable_edge_case_handling = (
            os.getenv("ENABLE_EDGE_CASES", "true").lower() == "true"
        )

        # Performance Configuration
        config.performance.enable_caching = os.getenv("ENABLE_CACHING", "true").lower() == "true"
        config.performance.cache_size_mb = int(os.getenv("CACHE_SIZE_MB", "100"))
        config.performance.enable_metrics = os.getenv("ENABLE_METRICS", "true").lower() == "true"

        # Logging Configuration
        config.logging.level = os.getenv("LOG_LEVEL", "INFO")
        config.logging.enable_file_logging = (
            os.getenv("ENABLE_FILE_LOGGING", "false").lower() == "true"
        )
        config.logging.log_file_path = os.getenv("LOG_FILE_PATH", "fantasy_optimizer.log")

        # Feature Flags
        config.enable_llm_enhancement = (
            os.getenv("ENABLE_LLM_ENHANCEMENT", "true").lower() == "true"
        )
        config.enable_hybrid_mode = os.getenv("ENABLE_HYBRID_MODE", "true").lower() == "true"
        config.enable_fallback_mode = os.getenv("ENABLE_FALLBACK_MODE", "true").lower() == "true"

        # Environment
        config.environment = Environment(os.getenv("ENVIRONMENT", Environment.DEVELOPMENT.value))

        # Rate Limiting
        config.max_optimizations_per_minute = int(os.getenv("MAX_OPTIMIZATIONS_PER_MINUTE", "10"))
        config.max_interactions_per_minute = int(os.getenv("MAX_INTERACTIONS_PER_MINUTE", "30"))

        return config

    @classmethod
    def for_development(cls) -> "HybridOptimizerConfig":
        """Create development configuration."""
        config = cls()
        config.environment = Environment.DEVELOPMENT
        config.llm.model = LLMModel.GPT_4O_MINI  # Cheaper model for development
        config.optimization.max_workers = 2  # Fewer workers for development
        config.optimization.genetic_population_size = 100  # Smaller population
        config.optimization.genetic_generations = 50  # Fewer generations
        config.performance.enable_profiling = True
        config.logging.level = "DEBUG"
        config.logging.enable_file_logging = True
        return config

    @classmethod
    def for_production(cls) -> "HybridOptimizerConfig":
        """Create production configuration."""
        config = cls()
        config.environment = Environment.PRODUCTION
        config.llm.model = LLMModel.GPT_4O  # Best model for production
        config.optimization.max_workers = 8  # More workers for production
        config.optimization.genetic_population_size = 2000  # Larger population
        config.optimization.genetic_generations = 300  # More generations
        config.performance.enable_profiling = False
        config.logging.level = "INFO"
        config.logging.enable_file_logging = True
        config.strict_validation = True
        return config

    @classmethod
    def for_testing(cls) -> "HybridOptimizerConfig":
        """Create testing configuration."""
        config = cls()
        config.environment = Environment.DEVELOPMENT
        config.enable_llm_enhancement = False  # Disable LLM for testing
        config.optimization.max_workers = 1  # Single worker for testing
        config.optimization.genetic_population_size = 10  # Very small population
        config.optimization.genetic_generations = 5  # Very few generations
        config.performance.enable_caching = False  # Disable caching for testing
        config.logging.level = "WARNING"  # Reduce log noise
        config.strict_validation = True
        return config

    def validate(self) -> List[str]:
        """Validate the configuration and return any issues."""
        issues = []

        # Validate LLM configuration
        if self.enable_llm_enhancement and not self.llm.api_key:
            issues.append("LLM API key is required when LLM enhancement is enabled")

        if self.llm.temperature < 0 or self.llm.temperature > 2:
            issues.append("LLM temperature must be between 0 and 2")

        if self.llm.max_tokens < 1 or self.llm.max_tokens > 4000:
            issues.append("LLM max tokens must be between 1 and 4000")

        if self.llm.timeout_seconds < 1 or self.llm.timeout_seconds > 300:
            issues.append("LLM timeout must be between 1 and 300 seconds")

        # Validate optimization configuration
        if self.optimization.max_workers < 1 or self.optimization.max_workers > 32:
            issues.append("Max workers must be between 1 and 32")

        if (
            self.optimization.genetic_population_size < 10
            or self.optimization.genetic_population_size > 10000
        ):
            issues.append("Genetic population size must be between 10 and 10000")

        if (
            self.optimization.genetic_generations < 1
            or self.optimization.genetic_generations > 1000
        ):
            issues.append("Genetic generations must be between 1 and 1000")

        if (
            self.optimization.genetic_mutation_rate < 0
            or self.optimization.genetic_mutation_rate > 1
        ):
            issues.append("Genetic mutation rate must be between 0 and 1")

        if (
            self.optimization.genetic_crossover_rate < 0
            or self.optimization.genetic_crossover_rate > 1
        ):
            issues.append("Genetic crossover rate must be between 0 and 1")

        # Validate performance configuration
        if self.performance.cache_size_mb < 1 or self.performance.cache_size_mb > 1000:
            issues.append("Cache size must be between 1 and 1000 MB")

        if (
            self.performance.metrics_retention_days < 1
            or self.performance.metrics_retention_days > 365
        ):
            issues.append("Metrics retention must be between 1 and 365 days")

        # Validate rate limiting
        if self.max_optimizations_per_minute < 1 or self.max_optimizations_per_minute > 100:
            issues.append("Max optimizations per minute must be between 1 and 100")

        if self.max_interactions_per_minute < 1 or self.max_interactions_per_minute > 1000:
            issues.append("Max interactions per minute must be between 1 and 1000")

        return issues

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "environment": self.environment.value,
            "llm": {
                "model": self.llm.model.value,
                "temperature": self.llm.temperature,
                "max_tokens": self.llm.max_tokens,
                "timeout_seconds": self.llm.timeout_seconds,
                "retry_attempts": self.llm.retry_attempts,
                "enable_caching": self.llm.enable_caching,
                "cache_ttl_seconds": self.llm.cache_ttl_seconds,
                "api_key_set": bool(self.llm.api_key),
            },
            "optimization": {
                "max_workers": self.optimization.max_workers,
                "use_genetic_algorithm": self.optimization.use_genetic_algorithm,
                "genetic_population_size": self.optimization.genetic_population_size,
                "genetic_generations": self.optimization.genetic_generations,
                "genetic_mutation_rate": self.optimization.genetic_mutation_rate,
                "genetic_crossover_rate": self.optimization.genetic_crossover_rate,
                "enable_parallel_processing": self.optimization.enable_parallel_processing,
                "max_alternatives": self.optimization.max_alternatives,
            },
            "enhancement": {
                "enable_explanations": self.enhancement.enable_explanations,
                "enable_alternatives": self.enhancement.enable_alternatives,
                "enable_edge_case_handling": self.enhancement.enable_edge_case_handling,
                "enable_strategy_adaptation": self.enhancement.enable_strategy_adaptation,
                "enable_user_interactions": self.enhancement.enable_user_interactions,
                "enable_context_analysis": self.enhancement.enable_context_analysis,
                "max_explanation_length": self.enhancement.max_explanation_length,
                "max_alternatives_count": self.enhancement.max_alternatives_count,
            },
            "performance": {
                "enable_caching": self.performance.enable_caching,
                "cache_size_mb": self.performance.cache_size_mb,
                "enable_compression": self.performance.enable_compression,
                "enable_metrics": self.performance.enable_metrics,
                "metrics_retention_days": self.performance.metrics_retention_days,
                "enable_profiling": self.performance.enable_profiling,
            },
            "logging": {
                "level": self.logging.level,
                "format": self.logging.format,
                "enable_file_logging": self.logging.enable_file_logging,
                "log_file_path": self.logging.log_file_path,
                "max_file_size_mb": self.logging.max_file_size_mb,
                "backup_count": self.logging.backup_count,
            },
            "feature_flags": {
                "enable_llm_enhancement": self.enable_llm_enhancement,
                "enable_hybrid_mode": self.enable_hybrid_mode,
                "enable_fallback_mode": self.enable_fallback_mode,
            },
            "defaults": {
                "default_strategy": self.default_strategy.value,
                "fallback_strategy": self.fallback_strategy.value,
            },
            "rate_limiting": {
                "max_optimizations_per_minute": self.max_optimizations_per_minute,
                "max_interactions_per_minute": self.max_interactions_per_minute,
            },
            "validation": {
                "strict_validation": self.strict_validation,
                "validate_player_data": self.validate_player_data,
                "validate_lineup_constraints": self.validate_lineup_constraints,
            },
        }


# Global configuration instance
_config: Optional[HybridOptimizerConfig] = None


def get_config() -> HybridOptimizerConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = HybridOptimizerConfig.from_environment()
    return _config


def set_config(config: HybridOptimizerConfig):
    """Set the global configuration instance."""
    global _config
    _config = config


def reset_config():
    """Reset the global configuration instance."""
    global _config
    _config = None


# Environment-specific configuration helpers
def setup_development_config():
    """Setup development configuration."""
    set_config(HybridOptimizerConfig.for_development())


def setup_production_config():
    """Setup production configuration."""
    set_config(HybridOptimizerConfig.for_production())


def setup_testing_config():
    """Setup testing configuration."""
    set_config(HybridOptimizerConfig.for_testing())
