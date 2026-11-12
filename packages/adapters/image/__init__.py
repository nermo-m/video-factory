"""Picture adapters: the interface and its demo twin (design doc section 3.3)."""

from packages.adapters.image.base import ImageAdapter, ImageRequest, ImageResult, png_size
from packages.adapters.image.samples import SampleImages

__all__ = ["ImageAdapter", "ImageRequest", "ImageResult", "SampleImages", "png_size"]
