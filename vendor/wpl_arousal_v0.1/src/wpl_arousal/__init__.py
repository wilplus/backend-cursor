"""wpl_arousal: Willpower Lab Step 2 model (engagement -> arousal -> valence -> clarity) for POST /analyze-take.
Research prototype. Trained on nEMO (CC BY-NC-SA 4.0): non-commercial use only. See LICENSES.md."""
from .core import build_baseline, analyze_take, thresholds, __version__, SCHEMA, ORDER
from .models import warmup

__all__ = ["build_baseline", "analyze_take", "thresholds", "warmup", "__version__", "SCHEMA", "ORDER"]
