from __future__ import annotations

from .extractor_common import ExtractorBase
from .inference_algorithms import InferenceAlgorithmsMixin
from .inference_scheduler import InferenceSchedulingMixin


class InferenceExtractor(
    InferenceSchedulingMixin,
    InferenceAlgorithmsMixin,
    ExtractorBase,
):
    """Exact inference engine with global character scheduling."""

    pass
