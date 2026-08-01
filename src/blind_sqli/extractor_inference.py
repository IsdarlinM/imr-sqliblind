from __future__ import annotations

from .extractor_common import ExtractorBase
from .inference_algorithms import InferenceAlgorithmsMixin
from .turbo_scheduler import TurboSchedulingMixin


class InferenceExtractor(
    TurboSchedulingMixin,
    InferenceAlgorithmsMixin,
    ExtractorBase,
):
    """Exact inference engine with global character scheduling."""

    pass
