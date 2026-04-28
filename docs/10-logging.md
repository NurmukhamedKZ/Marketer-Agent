# Logging (structlog)

File: `logging_setup.py`

```python
import structlog
import logging
from mktg_agent.config import get_settings

def setup_logging():
    settings = get_settings()
    
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
    ]
    
    if settings.log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()
    
    structlog.configure(
        processors=shared_processors + [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        cache_logger_on_first_use=True,
    )
```

## Logging Requirements

Every component must:

- Bind context: `log = log.bind(component="cmo_agent", run_id=uuid4())`
- Log start/end of each phase with duration
- Log every tool call (tool name, duration, error if any)
- Log all state transitions
